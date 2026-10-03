"""Reading a candidate's bytes on demand.

Strategies describe where a file's bytes are; they do not read them. A
filesystem hit carries ``metadata["extents"]`` (volume offset and length per
piece, offset ``-1`` for a hole that reads as zeros), a carved hit carries a
single ``data_offset``, and tiny files kept inside a filesystem record carry
``metadata["inline_data"]``. :class:`CandidateData` hides the difference and
exposes the file as one flat byte range, so previews, validators and the
writer all read the same way and never need the whole file in memory.
"""

from __future__ import annotations

import bisect
from typing import Iterator

from tizorecover.engine.results import FileCandidate

HOLE = -1
CHUNK = 4 << 20


def pieces_of(candidate: FileCandidate) -> list[tuple[int, int]]:
    """The candidate's ``(volume_offset, length)`` pieces, in file order."""
    extents = candidate.metadata.get("extents")
    if extents:
        return [(int(o), int(n)) for o, n in extents]
    if candidate.data_offset >= 0:
        return [(candidate.data_offset, candidate.size)]
    return []


class CandidateData:
    """One recovered file as a flat, read-only byte range.

    Implements the ``ByteSource`` protocol (``at`` and ``size``), so a
    format resolver can validate a recovered file exactly as it validates
    raw volume bytes.
    """

    def __init__(self, candidate: FileCandidate, src) -> None:
        self.candidate = candidate
        self.src = src
        self.inline = candidate.metadata.get("inline_data")
        self.pieces = [] if self.inline is not None else pieces_of(candidate)
        self.starts: list[int] = []
        total = 0
        for _off, length in self.pieces:
            self.starts.append(total)
            total += length
        self.size = len(self.inline) if self.inline is not None else min(total, candidate.size or total)

    def at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        if self.inline is not None:
            return bytes(self.inline[offset:offset + length])
        out = bytearray()
        index = max(0, bisect.bisect_right(self.starts, offset) - 1)
        pos = offset
        while length > 0 and index < len(self.pieces):
            vol_off, piece_len = self.pieces[index]
            inner = pos - self.starts[index]
            take = min(piece_len - inner, length)
            if take <= 0:
                index += 1
                continue
            if vol_off == HOLE:
                block = b"\x00" * take
            else:
                block = self.src.at(vol_off + inner, take)
                if len(block) < take:
                    block = block + b"\x00" * (take - len(block))
            out += block
            pos += take
            length -= take
            index += 1
        return bytes(out)

    def chunks(self, chunk: int = CHUNK, start: int = 0,
               end: int | None = None) -> Iterator[bytes]:
        end = self.size if end is None else min(end, self.size)
        pos = start
        while pos < end:
            block = self.at(pos, min(chunk, end - pos))
            if not block:
                return
            yield block
            pos += len(block)

    def read_all(self) -> bytes:
        return b"".join(self.chunks())


def read_all(candidate: FileCandidate, src) -> bytes:
    """The whole file. Fine for tests and small files; stream big ones."""
    return CandidateData(candidate, src).read_all()
