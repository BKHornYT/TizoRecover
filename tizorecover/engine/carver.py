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
from typing import Callable, Iterable, Iterator

from tizorecover.engine.blockdev import DEFAULT_CHUNK
from tizorecover.engine.formats import BY_MAGIC, FORMATS, MAX_MAGIC, Format, Extent
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

MIN_SIZE = 8
HEARTBEAT = 64


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
        ext=fmt.ext,
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


def _header_hits(buf: bytes, buf_off: int, formats: set[Format]) -> Iterator[tuple[int, Format]]:
    for magic, candidates in BY_MAGIC.items():
        matched = [f for f in candidates if f in formats]
        if not matched:
            continue
        start = 0
        while True:
            idx = buf.find(magic, start)
            if idx < 0:
                break
            for fmt in matched:
                yield buf_off + idx - fmt.back, fmt
            start = idx + 1


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
    """Forward-carve every recognisable file in ``[start, end)``."""
    wanted = tuple(formats) if formats is not None else FORMATS
    wanted_set = set(wanted)
    end = src.size if end is None else min(end, src.size)
    claims = _Claims()
    overlap = MAX_MAGIC
    pos = start
    scanned = 0
    pulses = 0

    while pos < end:
        if should_stop is not None and should_stop():
            return
        want = min(chunk + overlap, end - pos)
        buf = src.at(pos, want)
        if not buf:
            return
        # Empty space (zeros, or 0xFF on erased flash) holds no headers; one
        # comparison skips it at memory speed instead of a search per magic.
        if _blank(buf):
            pos += chunk
            scanned += want
            if progress is not None:
                progress(want)
            if len(buf) < want:
                return
            continue
        for offset, fmt in _header_hits(buf, pos, wanted_set):
            # Resolving a hit reads that file's whole extent, so a chunk full
            # of video can take minutes. A zero-byte pulse keeps the caller
            # informed without corrupting its byte total.
            pulses += 1
            if progress is not None and pulses % HEARTBEAT == 0:
                progress(0)
            if offset < pos or offset >= end:
                continue
            if claims.claimed(offset, offset + 1):
                continue
            resolver = fmt.resolve
            if resolver is None:
                continue
            try:
                extent = resolver(src, offset, end)
            except Exception:
                continue
            if extent is None or extent.size < min_size:
                continue
            stop = offset + extent.size
            if stop > src.size:
                continue
            claims.add(offset, stop)
            cand = _candidate(fmt, src, offset, extent, volume)
            if on_found is not None:
                on_found(cand)
            yield cand
        pos += chunk
        scanned += want
        if progress is not None:
            progress(want)
        if len(buf) < want:
            return


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
