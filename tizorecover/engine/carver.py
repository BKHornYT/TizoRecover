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
import re
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Iterable, Iterator

from tizorecover.engine.blockdev import DEFAULT_CHUNK
from tizorecover.engine.formats import BY_MAGIC, FORMATS, MAX_MAGIC, Format, Extent
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

MIN_SIZE = 8
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


def _trie_pattern(words: list[bytes]) -> bytes:
    """One regex shaped like a prefix tree of the magics.

    Python's ``re`` tries the branches of a flat alternation one by one at
    every byte; factoring the shared prefixes lets it rule out most positions
    on the first byte (~35% faster over real data, same hits).
    """
    trie: dict = {}
    for word in words:
        node = trie
        for b in word:
            node = node.setdefault(b, {})
        node[None] = True

    def build(node: dict) -> bytes:
        alts = [re.escape(bytes([b])) + build(child)
                for b, child in sorted((k, v) for k, v in node.items() if k is not None)]
        if not alts:
            return b""
        body = alts[0] if len(alts) == 1 else b"(?:" + b"|".join(alts) + b")"
        return b"(?:" + body + b")?" if None in node else body

    return build(trie)


_MAGIC_RE = re.compile(_trie_pattern(list(BY_MAGIC)))
# The regex returns the longest magic at a position; a shorter magic that is
# its prefix must still get its turn.
_MAGIC_FORMATS = {m: [f for w in BY_MAGIC if m.startswith(w) for f in BY_MAGIC[w]] for m in BY_MAGIC}


def _header_hits(buf: bytes, buf_off: int, formats: set[Format]) -> Iterator[tuple[int, int, Format]]:
    """Every (magic index, file offset, format) whose magic is in ``buf``, in disk order.

    One regex pass finds all magics at C speed; each hit is then put through
    the format's in-memory ``quick`` check, so the common false alarms (an
    ``MZ`` or an MPEG frame sync inside some video) never cost a disk read.
    """
    for m in _MAGIC_RE.finditer(buf):
        idx = m.start()
        for fmt in _MAGIC_FORMATS[m.group()]:
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

    def __init__(self, src) -> None:
        self._src = src
        self.size = src.size
        self._blocks: dict[int, bytes] = {}

    def _block(self, index: int) -> bytes:
        got = self._blocks.get(index)
        if got is None:
            if len(self._blocks) >= self.KEEP:
                self._blocks.pop(next(iter(self._blocks)))
            got = self._src.at(index * self.BLOCK, self.BLOCK)
            self._blocks[index] = got
        else:
            self._blocks[index] = self._blocks.pop(index)  # most recently used last
        return got

    def at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        if length > 2 * self.BLOCK:
            return self._src.at(offset, length)
        first, last = offset // self.BLOCK, (offset + length - 1) // self.BLOCK
        if first == last:
            start = offset - first * self.BLOCK
            return self._block(first)[start:start + length]
        data = b"".join(self._block(i) for i in range(first, last + 1))
        start = offset - first * self.BLOCK
        return data[start:start + length]


class _Prefetch:
    """Reads the next chunk on a helper thread while this one is searched."""

    def __init__(self, src) -> None:
        self._src = src
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tizo-read")
        self._next: tuple[int, int, Future] | None = None

    def get(self, pos: int, want: int) -> bytes:
        nxt = self._next
        self._next = None
        if nxt is not None and nxt[0] == pos and nxt[1] == want:
            return nxt[2].result()
        return self._src.at(pos, want)

    def ahead(self, pos: int, want: int) -> None:
        if want > 0:
            self._next = (pos, want, self._pool.submit(self._src.at, pos, want))

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)


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
) -> Iterator[FileCandidate]:
    """Forward-carve every recognisable file in ``[start, end)``.

    Hits are handled in disk order and a found file's bytes are skipped (not
    even read), the way PhotoRec does it: a photo embedded in a video is part
    of the video, not a file of its own, and a long video costs no searching.
    """
    wanted = tuple(formats) if formats is not None else FORMATS
    wanted_set = set(wanted)
    end = src.size if end is None else min(end, src.size)
    overlap = MAX_MAGIC
    pos = start
    skip_until = start
    pulses = 0
    reader = _Prefetch(src)
    walk_src = CachedSource(src)
    try:
        while pos < end:
            if should_stop is not None and should_stop():
                return
            if skip_until > pos:
                # Inside a file already found: jump over it without reading.
                jump = min(skip_until, end) - pos
                pos += jump
                if progress is not None:
                    progress(jump)
                continue
            want = min(chunk + overlap, end - pos)
            buf = reader.get(pos, want)
            if not buf:
                return
            if pos + chunk < end:
                reader.ahead(pos + chunk, min(chunk + overlap, end - pos - chunk))
            # Empty space (zeros, or 0xFF on erased flash) holds no headers; one
            # comparison skips it at memory speed instead of a search.
            if not _blank(buf):
                for idx, offset, fmt in _header_hits(buf, pos, wanted_set):
                    if idx >= chunk and pos + chunk < end:
                        continue                         # seen again, whole, in the next chunk
                    pulses += 1
                    if pulses % HEARTBEAT == 0:
                        if progress is not None:
                            progress(0)
                        if should_stop is not None and should_stop():
                            return
                    if offset < max(start, skip_until) or offset >= end:
                        continue
                    resolver = fmt.resolve
                    if resolver is None:
                        continue
                    try:
                        extent = resolver(walk_src, offset, end)
                    except Exception:
                        continue
                    if extent is None or extent.size < min_size:
                        continue
                    stop = offset + extent.size
                    if stop > src.size:
                        continue
                    skip_until = stop
                    cand = _candidate(fmt, walk_src, offset, extent, volume)
                    if on_found is not None:
                        on_found(cand)
                    yield cand
            # A file found here may run past this chunk; the jump at the top
            # of the loop counts the rest of it.
            step = min(chunk, end - pos)
            pos += step
            if progress is not None:
                progress(step)
            if len(buf) < want:
                return
    finally:
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
