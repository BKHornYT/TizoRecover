"""Signature carving: find files by their bytes, not by their metadata.

This is the strategy that works when the filesystem is wrecked, when the
file system itself cannot be parsed, or when a file is so fragmented that
no directory entry could ever point at it again. It knows nothing about
filesystems, so it also runs on top of a healthy volume as a safety net.

Two passes run here:

* forward — find headers, then ask the format how long the file is;
* backward — find footers (``IEND``, ``%%EOF``, EOCD) and search backwards
  for a header, which rescues a file whose start was overwritten.
"""

from __future__ import annotations

import bisect
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Iterable, Iterator

from tizorecover.engine.blockdev import DEFAULT_CHUNK, DriveGoneError
from tizorecover.engine.formats import BY_MAGIC, FORMATS, MAX_MAGIC, Format, Extent
from tizorecover.engine.magicsearch import ALL_MAGICS, EXTRA_MAGICS, MAX_MAGIC as SEARCH_MAGIC, find_magics
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

MIN_SIZE = 8
RECORD_READ = 4096                 # bytes handed to on_record: the largest MFT record size
WALK_CACHE_BLOCKS = 128            # 4 MiB blocks the carver keeps (512 MiB): a file walked ahead is not read again
HEARTBEAT = 16


class _Claims:
    """Byte ranges already taken, so nested hits are not double reported."""

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []

    def claimed(self, start: int, end: int) -> bool:
        i = bisect.bisect_right(self._starts, start) - 1
        while i >= 0 and self._ends[i] > start:
            if self._ends[i] > start and self._starts[i] < end:
                return True
            i -= 1
        return False

    def add(self, start: int, end: int) -> None:
        i = bisect.bisect_right(self._starts, start)
        self._starts.insert(i, start)
        self._ends.insert(i, end)


def _score(fmt: Format, extent: Extent) -> float:
    if extent.verdict is Verdict.VALID and extent.complete:
        return min(1.0, fmt.confidence + 0.1)
    if extent.verdict is Verdict.PARTIAL:
        return max(0.05, fmt.confidence - 0.3)
    if extent.verdict is Verdict.INVALID:
        return 0.0
    return fmt.confidence - 0.15


def _candidate(fmt: Format, src, offset: int, extent: Extent, volume: str) -> FileCandidate:
    verdict = extent.verdict
    reasons = list(extent.notes)
    if fmt.validate is not None:
        verdict, checks = fmt.validate(src, offset, extent.size)
        reasons.extend(checks)
    return FileCandidate(
        ext=extent.ext or fmt.ext,
        size=extent.size,
        data_offset=offset,
        strategy=Strategy.CARVE,
        verdict=verdict,
        confidence=_score(fmt, extent),
        reasons=reasons,
        volume=volume,
        metadata={"format": fmt.name, "category": fmt.category, "carved": True},
    )


_BLANK: dict[tuple[int, int], bytes] = {}


def _blank(buf: bytes) -> bool:
    """True when ``buf`` is all 0x00 or all 0xFF."""
    first = buf[:1]
    if first not in (b"\x00", b"\xff"):
        return False
    key = (first[0], len(buf))
    ref = _BLANK.get(key)
    if ref is None:
        if len(_BLANK) > 8:
            _BLANK.clear()
        ref = _BLANK[key] = first * len(buf)
    return buf == ref


# The regex returns the longest magic at a position; a shorter magic that is
# its prefix must still get its turn.
_MAGIC_FORMATS = {m: [f for w in BY_MAGIC if m.startswith(w) for f in BY_MAGIC[w]] for m in ALL_MAGICS}
_RECORD_MAGICS = frozenset(EXTRA_MAGICS)


def _header_hits(buf: bytes, buf_off: int, formats: set[Format],
                 records: bool = False, spans: list[tuple[int, int]] | None = None) -> Iterator[tuple[int, int, Format | None]]:
    """Every (magic index, file offset, format) whose magic is in ``buf``, in disk order.

    One regex pass finds all magics at C speed (on several cores, see
    ``magicsearch``); each hit is then put through
    the format's in-memory ``quick`` check, so the common false alarms (an
    ``MZ`` or an MPEG frame sync inside some video) never cost a disk read.
    """
    for idx, stop in (spans if spans is not None else find_magics(buf)):
        magic = bytes(buf[idx:stop])
        if records and magic in _RECORD_MAGICS:
            yield idx, buf_off + idx, None         # a file-system record, not a file
        for fmt in _MAGIC_FORMATS[magic]:
            if fmt not in formats:
                continue
            i = idx - fmt.back
            if fmt.quick is not None and i >= 0 and not fmt.quick(buf, i):
                continue
            yield idx, buf_off + i, fmt


class CachedSource:
    """Small reads served from a few cached 1 MiB blocks.

    Format walkers step through a file a few bytes at a time (segment
    headers, box sizes, one byte at a time through JPEG data). On a raw
    device every one of those is a sector read, which made a single photo
    take half a minute on a USB stick; through this cache they cost a slice.
    """

    BLOCK = 1 << 20
    KEEP = 6

    def __init__(self, src, keep: int | None = None, block: int | None = None) -> None:
        self._src = src
        self.BLOCK = block or self.BLOCK
        self.size = src.size
        self.keep = keep or self.KEEP
        self._blocks: dict[int, bytes] = {}

    def _remember(self, index: int, data: bytes) -> None:
        if index in self._blocks:
            self._blocks.pop(index)
        elif len(self._blocks) >= self.keep:
            self._blocks.pop(next(iter(self._blocks)))
        self._blocks[index] = data

    pending = None                       # set by _Prefetch: a queued read covering an offset, if any

    def _block(self, index: int) -> bytes:
        got = self._blocks.get(index)
        if got is None:
            if self.pending is not None:
                hit = self.pending(index * self.BLOCK)
                if hit is not None:
                    self.feed(*hit)
                    got = self._blocks.get(index)
                    if got is not None:
                        return got
            got = self._src.at(index * self.BLOCK, self.BLOCK)
            self._remember(index, got)
        else:
            self._blocks[index] = self._blocks.pop(index)  # most recently used last
        return got

    def feed(self, offset: int, data: bytes) -> None:
        """Keep the whole blocks inside ``data`` (read at ``offset`` by someone else): no second read."""
        first = -(-offset // self.BLOCK)
        last = (offset + len(data)) // self.BLOCK
        for i in range(first, last):
            if i not in self._blocks:
                start = i * self.BLOCK - offset
                self._remember(i, bytes(data[start:start + self.BLOCK]))

    def span(self, offset: int, length: int) -> bytes | None:
        """``length`` bytes at ``offset`` if every block is already here, else None (nothing is read)."""
        if length <= 0:
            return b""
        first, last = offset // self.BLOCK, (offset + length - 1) // self.BLOCK
        if any(i not in self._blocks for i in range(first, last + 1)):
            return None
        return self._join(offset, length, first, last)

    def _join(self, offset: int, length: int, first: int, last: int) -> bytes:
        start = offset - first * self.BLOCK
        if first == last:
            return self._block(first)[start:start + length]
        parts = [self._block(first)[start:]]
        for i in range(first + 1, last):
            parts.append(self._block(i))
        parts.append(self._block(last)[:offset + length - last * self.BLOCK])
        return b"".join(parts)

    def at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        first, last = offset // self.BLOCK, (offset + length - 1) // self.BLOCK
        if last - first > 2:
            got = self.span(offset, length)
            return got if got is not None else self._src.at(offset, length)
        return self._join(offset, length, first, last)


class _Prefetch:
    """Keeps the next chunks coming on a helper thread while this one is searched.

    ``DEPTH`` reads are queued so the drive never waits for the search; what the
    cache already holds (a file check read it) is not asked for again, and a
    file check that needs bytes already on their way waits for that read
    instead of starting a second one: a USB stick serves one stream well, two
    badly.
    """

    DEPTH = 2
    REACH = 64                                   # chunks a file check may pull ahead (512 MiB)

    def __init__(self, src, cache: "CachedSource | None" = None) -> None:
        self._src = src
        self._cache = cache
        self._grid: tuple[int, int, int] | None = None   # (chunk step, read size, end) of the main pass
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tizo-read")
        self._queue: list[tuple[int, int, Future]] = []
        if cache is not None:
            cache.pending = self.pending

    def pending(self, offset: int) -> tuple[int, bytes] | None:
        """(start, bytes) of a queued read that covers ``offset``, waiting for it if needed.

        A file check reaching past the queue extends it, in the main pass's own chunks, so its bytes
        come in the one sequential stream and the main pass finds them queued instead of reading again.
        """
        for pos, want, fut in self._queue:
            if pos <= offset < pos + want:
                return pos, fut.result()
        if self._grid is None or not self._queue:
            return None
        step, want, end = self._grid
        nxt = self._queue[-1][0] + step
        if not nxt <= offset < end or (offset - nxt) // step >= self.REACH:
            return None
        while nxt <= offset and nxt < end:
            w = min(want, end - nxt)
            self._queue.append((nxt, w, self._pool.submit(self._src.at, nxt, w)))
            nxt += step
        pos, w, fut = self._queue[-1]
        return (pos, fut.result()) if pos <= offset < pos + w else None

    def get(self, pos: int, want: int) -> bytes:
        while self._queue and self._queue[0][0] < pos:
            self._queue.pop(0)                    # passed over (a found file was jumped)
        if self._queue and self._queue[0][0] == pos and self._queue[0][1] == want:
            return self._queue.pop(0)[2].result()
        self._queue.clear()
        if self._cache is not None:
            got = self._cache.span(pos, want)
            if got is not None and len(got) == want:
                return got
        return self._src.at(pos, want)

    def ahead(self, pos: int, want: int, step: int | None = None, end: int | None = None) -> None:
        """Queue the read at ``pos`` and, when ``step``/``end`` are given, the ones after it up to DEPTH."""
        plan = [(pos, want)]
        if step is not None and end is not None:
            self._grid = (step, want, end)
            nxt = pos + step
            while len(plan) < self.DEPTH and nxt < end:
                plan.append((nxt, min(want, end - nxt)))
                nxt += step
        for p, w in plan:
            if w <= 0 or any(q[0] == p for q in self._queue):
                continue
            if self._cache is not None and self._cache.span(p, w) is not None:
                continue                         # a file check already read it
            self._queue.append((p, w, self._pool.submit(self._src.at, p, w)))

    def queued(self, pos: int) -> Future | None:
        """The read queued at ``pos``, if any (to start searching it as soon as it lands)."""
        return next((fut for p, _w, fut in self._queue if p == pos), None)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)


def carve_cache(src) -> "CachedSource":
    """The carver's cache: 512 MiB in 4 MiB reads. Pass the same one to ``carve_range`` and use it for
    whatever else reads the files it finds (naming, checks), and nothing is read twice."""
    return CachedSource(src, keep=WALK_CACHE_BLOCKS, block=4 << 20)


def carve_range(
    src,
    volume: str,
    start: int = 0,
    end: int | None = None,
    chunk: int = DEFAULT_CHUNK,
    formats: Iterable[Format] | None = None,
    min_size: int = MIN_SIZE,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_found: Callable[[FileCandidate], None] | None = None,
    on_record: Callable[[int, bytes], None] | None = None,
    on_chunk: Callable[[int, bytes, int], None] | None = None,
    align: tuple[int, int] | None = None,
    cache: "CachedSource | None" = None,
) -> Iterator[FileCandidate]:
    """Forward-carve every recognisable file in ``[start, end)``.

    Hits are handled in disk order and a found file's bytes are skipped, the
    way PhotoRec does it: a photo embedded in a video is part of the video,
    not a file of its own. But a file carved from leftovers often claims more
    than it really was (its end could not be pinned down), so with ``align``
    = ``(cluster size, where clusters start)`` a header exactly at a cluster
    start inside claimed bytes is still tried, and kept when its file checks
    out complete: files on a disk always start at a cluster. On the owner's
    stick that was 1,150 PNGs hidden behind long carved .gz/.exe files.

    ``on_record(offset, bytes)`` hears about every file-system record (an
    NTFS ``FILE`` record, a FAT folder's first cluster) in the space searched,
    with at least 4 KiB from its start; ``on_chunk(offset, bytes, length)``
    sees every chunk read (the first ``length`` bytes are its own). With
    either, claimed bytes are read too (records hide there as well).
    """
    wanted = tuple(formats) if formats is not None else FORMATS
    wanted_set = set(wanted)
    end = src.size if end is None else min(end, src.size)
    overlap = SEARCH_MAGIC
    pos = start
    skip_until = start
    claim_fmt: Format | None = None              # the type of the carved file whose bytes we are inside
    pulses = 0
    # One cache for the main pass and the format walkers: what one reads, the other never reads again.
    walk_src = cache or carve_cache(src)
    reader = _Prefetch(src, walk_src)
    read_claimed = on_record is not None or on_chunk is not None or align is not None
    # The magic search of the next chunk runs while this chunk's files are checked (two buffers in magicsearch).
    searcher = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tizo-search")
    searches: dict[int, Future] = {}

    def search_later(at: int) -> None:
        fut = reader.queued(at)
        if fut is None or at in searches:
            return
        searches[at] = searcher.submit(lambda f=fut: None if _blank(f.result()) else find_magics(f.result()))

    def at_cluster(offset: int) -> bool:
        return align is not None and offset >= align[1] and (offset - align[1]) % align[0] == 0

    def attempt(fmt: Format, offset: int, strict: bool) -> FileCandidate | None:
        resolver = fmt.resolve
        if resolver is None:
            return None
        try:
            extent = resolver(walk_src, offset, end)
        except DriveGoneError:
            raise
        except Exception:
            return None
        if extent is None or extent.size < min_size or offset + extent.size > src.size:
            return None
        if strict and not extent.complete:
            return None
        cand = _candidate(fmt, walk_src, offset, extent, volume)
        if strict and cand.verdict is not Verdict.VALID:
            return None
        return cand

    try:
        while pos < end:
            if should_stop is not None and should_stop():
                return
            claimed = skip_until > pos
            if claimed and not read_claimed:
                # Inside a file already found: jump over it without reading.
                jump = min(skip_until, end) - pos
                pos += jump
                if progress is not None:
                    progress(jump)
                continue
            # A fixed grid of chunks (claimed or not): the reads queued ahead always line up with what comes next.
            step = min(chunk, end - pos)
            want = min(step + overlap, end - pos)
            buf = reader.get(pos, want)
            if not buf:
                return
            walk_src.feed(pos, buf)
            if pos + step < end:
                reader.ahead(pos + step, min(chunk + overlap, end - pos - step), chunk, end)
                search_later(pos + step)
            pre = searches.pop(pos, None)
            spans = pre.result() if pre is not None else None
            for old in [k for k in searches if k < pos]:
                searches.pop(old)
            if on_chunk is not None:
                on_chunk(pos, buf, step)
            # Empty space (zeros, or 0xFF on erased flash) holds no headers; one
            # comparison skips it at memory speed instead of a search.
            if not _blank(buf):
                for idx, offset, fmt in _header_hits(buf, pos, wanted_set, on_record is not None, spans):
                    if idx >= step and pos + step < end:
                        continue                         # seen again, whole, in the next chunk
                    if fmt is None:
                        raw = buf[idx:idx + RECORD_READ]
                        if len(raw) < RECORD_READ:
                            raw = walk_src.at(offset, RECORD_READ)
                        on_record(offset, raw)
                        continue
                    pulses += 1
                    if pulses % HEARTBEAT == 0:
                        if progress is not None:
                            progress(0)
                        if should_stop is not None and should_stop():
                            return
                    if offset < start or offset >= end:
                        continue
                    inside = offset < skip_until
                    if inside and not at_cluster(offset):
                        continue
                    cand = attempt(fmt, offset, strict=inside)
                    if cand is None:
                        continue
                    if inside and fmt is claim_fmt and offset + cand.size == skip_until:
                        # Same type, same last byte: the tail of that file (an MP3 frame that happened to sit at a
                        # cluster start), not a file of its own. A 52 MB MP3 was listed three times.
                        continue
                    if inside:
                        cand.reasons.append("starts at a cluster inside bytes an earlier carved file claimed")
                    if offset + cand.size > skip_until:
                        skip_until, claim_fmt = offset + cand.size, fmt
                    if on_found is not None:
                        on_found(cand)
                    yield cand
            # A file found here may run past this chunk; the next round reads
            # (or, with nothing to look for there, jumps over) the rest of it.
            pos += step
            if progress is not None:
                progress(step)
            if len(buf) < want:
                return
    finally:
        searcher.shutdown(wait=True, cancel_futures=True)
        reader.close()


ORPHAN_FOOTERS: tuple[tuple[bytes, Format], ...] = tuple(
    (f.footer, f) for f in FORMATS if f.footer
)


def carve_orphans(
    src,
    volume: str,
    start: int = 0,
    end: int | None = None,
    chunk: int = DEFAULT_CHUNK,
    min_size: int = MIN_SIZE,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_found: Callable[[FileCandidate], None] | None = None,
    on_record: Callable[[int, bytes], None] | None = None,
) -> Iterator[FileCandidate]:
    """Recover files whose header is gone but whose tail survived.

    Each footer is located first, then the nearest plausible header is
    searched for backwards. A hit that no longer lines up with its own
    footer is reported as a fragment, which is more honest than claiming a
    clean file.
    """
    end = src.size if end is None else min(end, src.size)
    claims = _Claims()
    pos = start
    while pos < end:
        if should_stop is not None and should_stop():
            return
        buf = src.at(pos, min(chunk, end - pos))
        if not buf:
            return
        for footer, fmt in ORPHAN_FOOTERS:
            if fmt.resolve is None:
                continue
            idx = 0
            while True:
                found = buf.find(footer, idx)
                if found < 0:
                    break
                idx = found + 1
                foot_off = pos + found
                if claims.claimed(max(start, foot_off - fmt.max_size), foot_off):
                    continue
                cand = _find_header_backwards(src, fmt, foot_off, end, min_size)
                if cand is None:
                    continue
                claims.add(cand.data_offset, foot_off + len(footer))
                if on_found is not None:
                    on_found(cand)
                yield cand
        pos += chunk
        if progress is not None:
            progress(len(buf))


def _find_header_backwards(
    src, fmt: Format, foot_off: int, end: int, min_size: int
) -> FileCandidate | None:
    window_start = max(0, foot_off - fmt.max_size)
    window = src.at(window_start, foot_off - window_start)
    if not window:
        return None
    best: tuple[int, Extent] | None = None
    for magic in fmt.magics:
        search = 0
        while True:
            found = window.rfind(magic, search)
            if found < 0:
                break
            search = found + 1
            offset = window_start + found
            if not _in_bounds(src, offset, foot_off):
                continue
            try:
                extent = fmt.resolve(src, offset, end)
            except DriveGoneError:
                raise
            except Exception:
                continue
            if extent is None or extent.size < min_size:
                continue
            if best is None or extent.size > best[1].size:
                best = (offset, extent)
    if best is None:
        return None
    offset, extent = best
    cand = _candidate(fmt, src, offset, extent, "")
    header_end = offset + extent.size
    if header_end < foot_off:
        missing = foot_off + len(fmt.footer or b"") - header_end
        cand.gaps = [(header_end, missing)]
        cand.metadata["orphan_footer"] = True
        cand.confidence = min(cand.confidence, 0.45)
        cand.reasons.append(
            f"footer at {foot_off:#x} lies {missing} bytes past where the header ends; fragment"
        )
    return cand


def _in_bounds(src, start: int, end: int) -> bool:
    return start >= 0 and end <= src.size and end - start >= 0


def name_candidate(cand: FileCandidate, ext_hint: str | None = None) -> FileCandidate:
    """Give an unnamed carved file a readable name based on its verdict."""
    if cand.name or cand.original_path:
        return cand
    stamp = f"{cand.data_offset:012x}"
    tag = {Verdict.VALID: "ok", Verdict.PARTIAL: "partial", Verdict.SUSPECT: "suspect"}.get(
        cand.verdict, "suspect"
    )
    ext = ext_hint or cand.ext or "bin"
    cand.name = f"recovered_{stamp}_{tag}.{ext}"
    return cand
