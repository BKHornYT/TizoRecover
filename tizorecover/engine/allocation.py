"""Which parts of a volume are in use right now.

Two questions depend on it. Has a deleted file's space been handed to
another file since (then its bytes are someone else's now)? And where should
a deep scan look? Deleted data lives only in free space, so carving the
allocated part of a volume just rediscovers files that still exist and buries
the real finds among them.
"""

from __future__ import annotations

import re
from typing import Iterator

from tizorecover.engine.fs import exfat as exfat_fs
from tizorecover.engine.fs import ext4 as ext_fs
from tizorecover.engine.fs import fat as fat_fs
from tizorecover.engine.fs import ntfs as ntfs_fs

_RUNS = re.compile(rb"\x00+|\xff+|[^\x00\xff]")


class Allocation:
    """A per-cluster in-use map over a byte range of the volume.

    ``used`` holds one byte per cluster (0 free, 1 in use); clusters sit at
    ``base + index * unit`` in volume bytes.
    """

    def __init__(self, kind: str, unit: int, base: int, used: bytes) -> None:
        self.kind = kind
        self.unit = unit
        self.base = base
        self.used = used

    @property
    def free_bytes(self) -> int:
        return self.used.count(0) * self.unit

    def _index(self, offset: int) -> int:
        return (offset - self.base) // self.unit

    def used_fraction(self, extents: list[tuple[int, int]]) -> float:
        """Share of the bytes in ``extents`` whose clusters are in use now."""
        total = 0
        taken = 0
        for offset, length in extents:
            if offset < 0 or length <= 0:
                continue
            first = max(0, self._index(offset))
            last = min(len(self.used) - 1, self._index(offset + length - 1))
            if last < first:
                continue
            span = self.used[first:last + 1]
            total += len(span)
            taken += len(span) - span.count(0)
        return taken / total if total else 0.0

    def free_ranges(self, min_length: int = 0) -> Iterator[tuple[int, int]]:
        """``(offset, length)`` of every run of free clusters, in volume bytes."""
        for match in re.finditer(rb"\x00+", self.used):
            length = (match.end() - match.start()) * self.unit
            if length >= min_length:
                yield self.base + match.start() * self.unit, length


def _expand_bitmap(bitmap: bytes, clusters: int) -> bytes:
    """NTFS ``$Bitmap`` (LSB-first bits) to one byte per cluster."""
    out = bytearray()
    for match in _RUNS.finditer(bitmap):
        chunk = match.group()
        if chunk[0] == 0x00:
            out += b"\x00" * (8 * len(chunk))
        elif chunk[0] == 0xFF:
            out += b"\x01" * (8 * len(chunk))
        else:
            value = chunk[0]
            out += bytes((value >> bit) & 1 for bit in range(8))
    del out[clusters:]
    return bytes(out)


def from_ntfs(src) -> Allocation | None:
    boot = ntfs_fs.parse_boot_sector(src)
    if boot is None:
        return None
    mft_lcn = ntfs_fs.find_mft_start(src, boot)
    if mft_lcn is None:
        return None
    mft_map = ntfs_fs.MftMap.locate(src, boot, mft_lcn)
    bitmap = ntfs_fs.load_bitmap(src, boot, mft_lcn, mft_map)
    if not bitmap:
        return None
    clusters = min(len(bitmap) * 8, max(1, src.size // boot.cluster_size))
    return Allocation("ntfs", boot.cluster_size, 0, _expand_bitmap(bitmap, clusters))


def from_fat(src) -> Allocation | None:
    info = fat_fs.find_fat(src)
    if info is None:
        return None
    table = fat_fs.load_table(src, info)
    used = bytes(1 if v else 0 for v in table[2:info.cluster_count + 2])
    return Allocation(f"fat{info.bits}", info.cluster_size, info.cluster_offset(2), used)


def from_exfat(src) -> Allocation | None:
    info = exfat_fs.find_exfat(src)
    if info is None:
        return None
    bitmap = exfat_fs.load_bitmap(src, info)
    if not bitmap:
        return None
    return Allocation("exfat", info.cluster_size, info.cluster_offset(2),
                      _expand_bitmap(bitmap, info.cluster_count))


def from_ext(src) -> Allocation | None:
    info = ext_fs.read_super(src)
    if info is None or not info.groups:
        return None
    return Allocation("ext", info.block, info.first_data_block * info.block, ext_fs.bitmap(src, info))


def detect(src, filesystem: str) -> Allocation | None:
    """The allocation map for ``filesystem``, or None when it cannot be read."""
    try:
        if filesystem == "ntfs":
            return from_ntfs(src)
        if filesystem in ("fat", "fat32"):
            return from_fat(src)
        if filesystem == "exfat":
            return from_exfat(src)
        if filesystem.startswith("ext"):
            return from_ext(src)
    except (OSError, ValueError, IndexError):
        return None
    return None
