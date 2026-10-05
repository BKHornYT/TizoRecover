"""The pieces every format module shares: Extent, Format, ByteSource and the blank-space finder.

Split out of formats.py so formats_extra.py can use them without importing formats.py
(which imports formats_extra at its end: importing formats_extra first was a circular import).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from tizorecover.engine.results import Verdict

KIB = 1024
MIB = 1024 * 1024
MIN_EXTENT = 32


class ByteSource(Protocol):
    size: int

    def at(self, offset: int, length: int) -> bytes: ...


@dataclass
class Extent:
    """How far a file of this type runs, and what we think of it."""

    size: int
    verdict: Verdict = Verdict.SUSPECT
    notes: list[str] = field(default_factory=list)
    complete: bool = True
    ext: str | None = None   # the real type when the contents say more than the magic (NEF in a TIFF)


@dataclass(eq=False)
class Format:
    name: str
    ext: str
    magics: tuple[bytes, ...]
    max_size: int = 64 * MIB
    footer: bytes | None = None
    resolve: Callable[[ByteSource, int, int], Extent | None] | None = None
    validate: Callable[[ByteSource, int, int], tuple[Verdict, list[str]]] | None = None
    category: str = "document"
    confidence: float = 0.5
    back: int = 0
    # Cheap test on the bytes already in memory (``buf`` holds the hit at
    # ``i``). False rejects without touching the disk; whatever it cannot see
    # (the header runs past ``buf``) must answer True and leave it to resolve.
    quick: Callable[[bytes, int], bool] | None = None


BLANK_BLOCK = 4096
_ZERO_BLOCK = b"\x00" * BLANK_BLOCK


def _until_blank(src: ByteSource, off: int, limit: int, cap: int) -> int:
    """Where data that has no length field most likely ends.

    Compressed media never holds 4 KiB of zeros, but the free space after a
    deleted file usually does, so the first zero block (or ``limit``, or
    ``cap``) is the best end there is. Returns an absolute offset.
    """
    end = min(limit, src.size, off + cap)
    pos = off
    step = 1 * MIB
    while pos < end:
        window = src.at(pos, min(step + BLANK_BLOCK, end - pos))
        if not window:
            break
        idx = window.find(_ZERO_BLOCK)
        if idx >= 0:
            return pos + idx
        if len(window) <= BLANK_BLOCK:
            break
        pos += len(window) - BLANK_BLOCK
    return end
