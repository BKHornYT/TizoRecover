"""Finding file systems that are no longer in the partition table.

Two disasters look alike to a user: a partition that was deleted, and a drive
that was formatted again. In both the old file system's structures usually
survive, because neither operation rewrites the whole drive:

* NTFS keeps a copy of its boot sector in the last sector of the volume, so a
  quick format (which rewrites the first one) leaves the old copy, and the old
  $MFT it points to, in place.
* FAT32 keeps a copy at sector 6, exFAT a copy of its boot region at sector 12.
* ext2/3/4 keep copies of the superblock at the start of block groups 1, 3, 5,
  7, 9, 25, 27, ... (every 128 MiB with 4 KiB blocks).

The search reads candidate sectors, recognises those structures, works out
where each file system started and how big it was, and hands back something
that scans like any partition. For a file system whose own first sector is
gone, ``boot_patch`` says which surviving copy to read in its place.

A *quick* search reads only the sectors around every 1 MiB boundary (where
every modern tool puts partitions, and where ext backups land); a *thorough*
search reads every sector.
"""

from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterator

from tizorecover.engine.blockdev import BlockReader

SECTOR = 512
MIB = 1 << 20
_EXT_GROUPS = (0, 1, 3, 5, 7, 9, 25, 27, 49, 81, 125, 243, 343, 625, 729)


@dataclass
class FoundFS:
    filesystem: str          # ntfs, fat32, exfat, ext
    start: int               # bytes from the start of what was searched
    size: int
    label: str = ""
    serial: str = ""
    found_by: str = ""
    boot_patch: int = -1     # where a surviving boot copy is, when the first one is gone
    patch_len: int = SECTOR
    current: bool = False    # the live file system, not a lost one
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- recognisers

def ntfs_boot(sec: bytes) -> dict | None:
    if len(sec) < SECTOR or sec[3:11] != b"NTFS    " or sec[510:512] != b"\x55\xaa":
        return None
    bps = struct.unpack_from("<H", sec, 0x0B)[0]
    spc = sec[0x0D]
    total = struct.unpack_from("<Q", sec, 0x28)[0]
    mft = struct.unpack_from("<Q", sec, 0x30)[0]
    if bps not in (512, 1024, 2048, 4096) or spc == 0 or total == 0:
        return None
    cluster = bps * (spc if spc < 0x80 else 1 << (256 - spc))
    return {"bps": bps, "cluster": cluster, "total": total, "size": total * bps,
            "mft": mft * cluster, "serial": sec[0x48:0x50][::-1].hex().upper()}


def fat32_boot(sec: bytes) -> dict | None:
    if len(sec) < SECTOR or sec[0x52:0x5A] != b"FAT32   " or sec[510:512] != b"\x55\xaa":
        return None
    bps = struct.unpack_from("<H", sec, 0x0B)[0]
    total = struct.unpack_from("<I", sec, 0x20)[0]
    backup = struct.unpack_from("<H", sec, 0x32)[0]
    if bps not in (512, 1024, 2048, 4096) or total == 0 or sec[0x0D] == 0:
        return None
    label = sec[0x47:0x52].decode("ascii", "replace").strip(" " + chr(0))
    return {"bps": bps, "size": total * bps, "backup_sector": backup,
            "reserved": struct.unpack_from("<H", sec, 0x0E)[0], "media": sec[0x15],
            "serial": sec[0x43:0x47][::-1].hex().upper(), "label": "" if label == "NO NAME" else label}


def exfat_boot(sec: bytes) -> dict | None:
    if len(sec) < SECTOR or sec[3:11] != b"EXFAT   " or sec[510:512] != b"\x55\xaa":
        return None
    bps_shift = sec[108]
    if not 9 <= bps_shift <= 12:
        return None
    total = struct.unpack_from("<Q", sec, 72)[0]
    return {"bps": 1 << bps_shift, "size": total << bps_shift,
            "fat": struct.unpack_from("<I", sec, 80)[0] << bps_shift,
            "serial": sec[100:104][::-1].hex().upper()}


def ext_super(sb: bytes) -> dict | None:
    """An ext2/3/4 superblock (1024 bytes), or None."""
    if len(sb) < 1024 or sb[0x38:0x3A] != b"\x53\xef":
        return None
    log = struct.unpack_from("<I", sb, 0x18)[0]
    if log > 6:
        return None
    block = 1024 << log
    count = struct.unpack_from("<I", sb, 0x04)[0]
    per_group = struct.unpack_from("<I", sb, 0x20)[0]
    features_incompat = struct.unpack_from("<I", sb, 0x60)[0]
    if features_incompat & 0x80:                       # 64-bit block counts
        count |= struct.unpack_from("<I", sb, 0x150)[0] << 32
    group = struct.unpack_from("<H", sb, 0x5A)[0]
    state = struct.unpack_from("<H", sb, 0x3A)[0]
    if count == 0 or per_group == 0 or per_group > 8 * block or state > 7:
        return None
    name = sb[0x78:0x88].split(b"\x00")[0].decode("utf-8", "replace")
    return {"block": block, "size": count * block, "per_group": per_group, "group": group,
            "uuid": sb[0x68:0x78].hex(), "label": name,
            "kind": "ext4" if features_incompat & 0x40 else ("ext3" if struct.unpack_from("<I", sb, 0x5C)[0] & 4 else "ext2")}


# ---------------------------------------------------------------- search

def _ext_start(pos_of_sb: int, info: dict) -> int:
    """Where the file system starts, given where this copy of its superblock was."""
    group = info["group"]
    if group == 0:
        return pos_of_sb - 1024
    span = info["per_group"] * info["block"]
    base = pos_of_sb - (1024 if info["block"] == 1024 else 0)
    return base - group * span


def _probe_offsets(size: int) -> Iterator[int]:
    """Sectors worth reading in a quick search: around every MiB boundary, plus old CHS spots."""
    yield 0
    yield 63 * SECTOR
    for mib in range(1, size // MIB + 1):
        yield mib * MIB - SECTOR      # last sector before the boundary (NTFS backups)
        yield mib * MIB               # boot sectors, ext backup superblocks (+1024 for group 0)


class Searcher:
    """Finds file systems in one reader (a disk, a volume or an image)."""

    def __init__(self, reader: BlockReader) -> None:
        self.reader = reader
        self.size = reader.size
        self.found: dict[tuple[str, int], FoundFS] = {}

    def _read(self, offset: int, length: int) -> bytes:
        if offset < 0 or offset >= self.size:
            return b""
        try:
            return self.reader.read_at(offset, min(length, self.size - offset))
        except OSError:
            return b""

    def _add(self, fs: FoundFS) -> None:
        if fs.start < 0 or fs.size <= 0 or fs.start + SECTOR > self.size:
            return
        key = (fs.filesystem, fs.start)
        old = self.found.get(key)
        if old is None or (old.boot_patch >= 0 and fs.boot_patch < 0):
            self.found[key] = fs

    # One sector at ``pos`` may be any of several structures.
    def examine(self, pos: int, sec: bytes) -> None:
        if (info := ntfs_boot(sec)) is not None:
            self._ntfs(pos, info)
        elif (info := fat32_boot(sec)) is not None:
            self._fat32(pos, info)
        elif (info := exfat_boot(sec)) is not None:
            self._exfat(pos, info)

    def examine_super(self, pos: int, sb: bytes) -> None:
        info = ext_super(sb)
        if info is None:
            return
        start = _ext_start(pos, info)
        how = "superblock" if info["group"] == 0 else f"backup superblock (group {info['group']})"
        self._add(FoundFS(info["kind"], start, info["size"], info["label"], info["uuid"][:8].upper(), how))

    def _ntfs(self, pos: int, info: dict) -> None:
        # Is this the volume's first sector, or the backup in its last one?
        primary = pos - info["size"]
        twin = ntfs_boot(self._read(primary, SECTOR)) if primary >= 0 else None
        if twin is not None and twin["serial"] == info["serial"]:
            return                                    # the backup of a boot sector seen on its own
        if self._mft_ok(pos, info):
            self._add(FoundFS("ntfs", pos, info["size"] + info["bps"], serial=info["serial"],
                              found_by="boot sector"))
        if primary >= 0 and self._mft_ok(primary, info):
            self._add(FoundFS("ntfs", primary, info["size"] + info["bps"], serial=info["serial"],
                              found_by="backup boot sector (the first one was overwritten)",
                              boot_patch=pos))

    def _mft_ok(self, start: int, info: dict) -> bool:
        return self._read(start + info["mft"], 4) == b"FILE"

    # A boot sector says where its FAT is; only the right start finds a FAT there.
    def _fat32_at(self, start: int, info: dict) -> bool:
        head = self._read(start + info["reserved"] * info["bps"], 4)
        return len(head) == 4 and head[0] == info["media"] and head[1:4] == b"\xff\xff\x0f"

    def _exfat_at(self, start: int, info: dict) -> bool:
        return self._read(start + info["fat"], 8) == b"\xf8" + b"\xff" * 7

    def _fat32(self, pos: int, info: dict) -> None:
        backup = info["backup_sector"] * info["bps"]
        if self._fat32_at(pos, info):
            self._add(FoundFS("fat32", pos, info["size"], info["label"], info["serial"], "boot sector"))
        elif (backup and pos >= backup and fat32_boot(self._read(pos - backup, SECTOR)) is None
              and self._fat32_at(pos - backup, info)):
            self._add(FoundFS("fat32", pos - backup, info["size"], info["label"], info["serial"],
                              "backup boot sector (the first one was overwritten)", boot_patch=pos))

    def _exfat(self, pos: int, info: dict) -> None:
        backup = 12 * info["bps"]
        if self._exfat_at(pos, info):
            self._add(FoundFS("exfat", pos, info["size"], serial=info["serial"], found_by="boot sector"))
        elif (pos >= backup and exfat_boot(self._read(pos - backup, SECTOR)) is None
              and self._exfat_at(pos - backup, info)):
            self._add(FoundFS("exfat", pos - backup, info["size"], serial=info["serial"],
                              found_by="backup boot region (the first one was overwritten)",
                              boot_patch=pos, patch_len=12 * info["bps"]))

    def quick(self, progress: Callable[[int], None] | None = None,
              should_stop: Callable[[], bool] | None = None) -> list[FoundFS]:
        last = 0
        for pos in _probe_offsets(self.size):
            if should_stop is not None and should_stop():
                break
            block = self._read(pos, 2 * 1024)
            if block:
                self.examine(pos, block[:SECTOR])
                if len(block) >= 2048:
                    self.examine_super(pos + 1024, block[1024:2048])
                    self.examine_super(pos, block[:1024])
            if progress is not None and pos - last >= 64 * MIB:
                progress(pos - last)
                last = pos
        if progress is not None:
            progress(max(0, self.size - last))
        return self.results()

    _SIGS = re.compile(rb"NTFS    |EXFAT   |FAT32   |\x53\xef")

    def thorough(self, progress: Callable[[int], None] | None = None,
                 should_stop: Callable[[], bool] | None = None, chunk: int = 8 * MIB) -> list[FoundFS]:
        pos = 0
        while pos < self.size:
            if should_stop is not None and should_stop():
                break
            buf = self._read(pos, chunk + 2048)
            if not buf:
                break
            for m in self._SIGS.finditer(buf, 0, min(len(buf), chunk + 0x60)):
                rel = m.start() % SECTOR
                at = m.start() - rel
                sig = m.group()
                if sig == b"\x53\xef":
                    if rel == 0x38:
                        sb = buf[at:at + 1024]
                        self.examine_super(pos + at, sb if len(sb) == 1024 else self._read(pos + at, 1024))
                elif (sig == b"FAT32   " and rel == 0x52) or (sig != b"FAT32   " and rel == 3):
                    self.examine(pos + at, buf[at:at + SECTOR])
            step = min(chunk, self.size - pos)
            pos += step
            if progress is not None:
                progress(step)
        return self.results()

    def results(self) -> list[FoundFS]:
        out = sorted(self.found.values(), key=lambda f: (f.start, f.filesystem))
        # One file system is often seen through several copies of its boot
        # sector or superblock. Copies left over from before a resize point at
        # slightly different starts, so keep one per serial: the copy found
        # through the real first sector when there is one, else the first.
        best: dict[tuple[str, str], FoundFS] = {}
        for f in out:
            if f.size <= 0:
                continue
            # ext copies carry the file system's UUID; boot sector copies are
            # already tied to one start, and blank serials are common there.
            key = (f.filesystem, f.serial if f.filesystem.startswith("ext") and f.serial else f"@{f.start}")
            have = best.get(key)
            first_copy = f.found_by in ("boot sector", "superblock")
            if have is None or (first_copy and have.found_by not in ("boot sector", "superblock")):
                best[key] = f
        return sorted(best.values(), key=lambda f: (f.start, f.filesystem))


def prune_overlaps(found: list[FoundFS]) -> list[FoundFS]:
    """Of lost file systems that overlap, keep the best evidenced one.

    A drive that was set up several times leaves backup superblocks of every
    generation behind; they all claim the same stretch. The one whose own
    first sector (or primary superblock) survived is the newest; the rest are
    older layers of the same space and only confuse the list.
    """
    def strength(f: FoundFS) -> tuple:
        return (f.found_by in ("boot sector", "superblock"), f.boot_patch >= 0, -f.start)

    kept: list[FoundFS] = []
    for f in sorted(found, key=strength, reverse=True):
        if all(f.start + f.size <= k.start or k.start + k.size <= f.start for k in kept):
            kept.append(f)
    return sorted(kept, key=lambda f: f.start)


def mark_current(found: list[FoundFS], live: list[tuple[int, int, str]]) -> list[FoundFS]:
    """Flag file systems that are the live ones (same start and type as a partition in use)."""
    for f in found:
        for start, _size, fs in live:
            if f.start == start and (fs or "").lower().startswith(f.filesystem[:3]):
                f.current = True
    return found


class PatchedReader(BlockReader):
    """A reader that shows a surviving boot copy where the overwritten original was."""

    def __init__(self, parent: BlockReader, patch: bytes) -> None:
        self.parent = parent
        self.patch = patch
        super().__init__(parent.size, parent.label)

    def read(self, offset: int, length: int) -> bytes:
        data = self.parent.read(offset, length)
        if offset < len(self.patch) and data:
            end = min(len(self.patch), offset + len(data))
            data = self.patch[offset:end] + data[end - offset:]
        return data

    def close(self) -> None:
        self.parent.close()
