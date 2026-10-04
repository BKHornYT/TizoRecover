"""FAT12/16/32: recover files from deleted directory entries.

Deleting a file overwrites the first byte of its directory entry with 0xE5
and frees its cluster chain. The long file name that precedes the short entry
often survives, which is how the real name comes back. Windows zeroes the
freed chain, so for a deleted file only the first cluster is known for sure;
the rest is found the way every FAT undelete tool does it: the file is
assumed to continue through the free clusters that follow its first one.
That is right for the common unfragmented case and is reported as an
assumption, not passed off as fact.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterator

from tizorecover.engine.results import FileCandidate, Strategy, Verdict

ATTR_LFN = 0x0F
ATTR_VOLUME = 0x08
DELETED_MARK = 0xE5
DIR_ATTR = 0x10
ROOT_INDEX = -1


@dataclass
class FatInfo:
    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    fats: int
    root_entries: int
    total_sectors: int
    fat_size: int
    root_cluster: int
    fat_start: int
    data_start: int
    cluster_count: int
    bits: int

    @property
    def cluster_size(self) -> int:
        return self.bytes_per_sector * self.sectors_per_cluster

    def cluster_offset(self, cluster: int) -> int:
        return self.data_start * self.bytes_per_sector + (cluster - 2) * self.cluster_size

    @property
    def root_dir_offset(self) -> int:
        """Byte offset of the fixed FAT12/16 root directory region."""
        return (self.reserved_sectors + self.fats * self.fat_size) * self.bytes_per_sector


def find_fat(src) -> FatInfo | None:
    head = src.at(0, 512)
    if len(head) < 512:
        return None
    bps = struct.unpack_from("<H", head, 0x0B)[0]
    spc = head[0x0D]
    if bps not in (512, 1024, 2048, 4096) or not 1 <= spc <= 128:
        return None
    reserved = struct.unpack_from("<H", head, 0x0E)[0]
    fats = head[0x10]
    root_entries = struct.unpack_from("<H", head, 0x11)[0]
    total16 = struct.unpack_from("<H", head, 0x13)[0]
    fat16 = struct.unpack_from("<H", head, 0x16)[0]
    total32 = struct.unpack_from("<I", head, 0x20)[0]
    fat32 = struct.unpack_from("<I", head, 0x24)[0]
    root_cluster = struct.unpack_from("<I", head, 0x2C)[0]
    # FAT12/16 keep the FAT size at 0x16; only FAT32 sets it to zero and uses
    # the 32-bit field at 0x24. Reading 0x24 alone rejects every FAT12/16.
    fat_size = fat16 or fat32
    if fats == 0 or reserved == 0 or fat_size == 0:
        return None
    if not (head[510:512] == b"\x55\xaa"):
        return None
    total = total16 or total32
    if total == 0:
        return None
    sig = head[0x52:0x5A]
    if sig == b"FAT32   " or (fat16 == 0 and total16 == 0):
        bits = 32
    elif head[0x36:0x3E] == b"FAT12   ":
        bits = 12
    elif head[0x36:0x3E] == b"FAT16   ":
        bits = 16
    else:
        hint = cluster_count_hint(total, reserved, fats, fat_size, bps, root_entries) // max(1, spc)
        bits = 32 if hint > 65524 else (16 if hint > 4084 else 12)
    root_entries = 0 if bits == 32 else root_entries
    data_start = reserved + fats * fat_size + (root_entries * 32 + bps - 1) // bps
    cluster_count = max(0, (total - data_start) // spc)
    if cluster_count <= 0:
        return None
    return FatInfo(bps, spc, reserved, fats, root_entries, total, fat_size,
                   root_cluster if bits == 32 else 0, reserved, data_start,
                   cluster_count, bits)


def cluster_count_hint(total: int, reserved: int, fats: int, fat_size: int,
                       bps: int, root_entries: int) -> int:
    data_start = reserved + fats * fat_size + (root_entries * 32 + bps - 1) // bps
    return max(0, total - data_start)


def _entry_offset(fat: FatInfo, index: int) -> int:
    if fat.bits == 32:
        return fat.fat_start * fat.bytes_per_sector + index * 4
    if fat.bits == 16:
        return fat.fat_start * fat.bytes_per_sector + index * 2
    return fat.fat_start * fat.bytes_per_sector + index + (index >> 1)


def read_fat_entry(src, fat: FatInfo, index: int) -> int:
    if index < 0 or index >= fat.cluster_count + 2:
        return 0xFFFFFFFF
    raw = src.at(_entry_offset(fat, index), 4 if fat.bits == 32 else 2)
    if fat.bits == 32:
        return struct.unpack("<I", raw)[0] & 0x0FFFFFFF
    if fat.bits == 16:
        return struct.unpack("<H", raw)[0]
    if len(raw) < 2:
        return 0xFFFFFFFF
    value = struct.unpack("<H", raw)[0]
    if index & 1:
        return value >> 4
    return value & 0x0FFF


def load_table(src, fat: FatInfo) -> list[int]:
    """Every FAT entry at once, so allocation checks are not one read each."""
    count = fat.cluster_count + 2
    start = fat.fat_start * fat.bytes_per_sector
    if fat.bits == 32:
        raw = src.at(start, count * 4)
        n = len(raw) // 4
        return [v & 0x0FFFFFFF for v in struct.unpack_from(f"<{n}I", raw)]
    if fat.bits == 16:
        raw = src.at(start, count * 2)
        n = len(raw) // 2
        return list(struct.unpack_from(f"<{n}H", raw))
    raw = src.at(start, (count * 3 + 1) // 2 + 1)
    out = []
    for index in range(count):
        off = index + (index >> 1)
        if off + 2 > len(raw):
            break
        value = raw[off] | (raw[off + 1] << 8)
        out.append(value >> 4 if index & 1 else value & 0x0FFF)
    return out


def is_end(value: int, bits: int = 32) -> bool:
    if bits == 12:
        return value >= 0xFF8
    if bits == 16:
        return value >= 0xFFF8
    return value >= 0x0FFFFFF8


def is_bad(value: int, bits: int = 32) -> bool:
    if bits == 12:
        return 0xFF0 <= value <= 0xFF7
    if bits == 16:
        return 0xFFF0 <= value <= 0xFFF7
    return 0x0FFFFFF0 <= value <= 0x0FFFFFF7


def read_chain(src, fat: FatInfo, start: int, limit: int = 1 << 22) -> list[int]:
    chain: list[int] = []
    seen: set[int] = set()
    current = start
    while 2 <= current < fat.cluster_count + 2 and current not in seen and len(chain) < limit:
        chain.append(current)
        seen.add(current)
        nxt = read_fat_entry(src, fat, current)
        if nxt == 0 or is_end(nxt, fat.bits) or is_bad(nxt, fat.bits):
            break
        if nxt == current:
            break
        current = nxt
    return chain


def deleted_chain(src, fat: FatInfo, start: int, size: int,
                  table: list[int] | None = None) -> tuple[list[int], bool]:
    """Clusters of a deleted file, and whether the chain had to be guessed.

    A chain still linked in the FAT and exactly as long as the file needs is
    used as it is. Otherwise the file is assumed to run on through the free
    clusters after its first one, skipping clusters that are in use now.
    """
    need = max(1, -(-size // fat.cluster_size))
    linked = read_chain(src, fat, start, limit=need + 1)
    if len(linked) == need:
        last = read_fat_entry(src, fat, linked[-1])
        if is_end(last, fat.bits):
            return linked, False
    chain = [start]
    cluster = start + 1
    end = fat.cluster_count + 2
    while len(chain) < need and cluster < end:
        value = table[cluster] if table is not None and cluster < len(table) \
            else read_fat_entry(src, fat, cluster)
        if value == 0:
            chain.append(cluster)
        cluster += 1
    return chain, True


def chain_extents(fat: FatInfo, chain: list[int], size: int) -> list[tuple[int, int]]:
    """``(byte_offset, length)`` pieces for a cluster chain, merged where adjacent."""
    out: list[tuple[int, int]] = []
    remaining = size
    for cluster in chain:
        if remaining <= 0:
            break
        offset = fat.cluster_offset(cluster)
        length = min(fat.cluster_size, remaining)
        if out and out[-1][0] + out[-1][1] == offset:
            out[-1] = (out[-1][0], out[-1][1] + length)
        else:
            out.append((offset, length))
        remaining -= length
    return out


def read_clusters(src, fat: FatInfo, chain: list[int], size: int) -> tuple[bytes, list[tuple[int, int]]]:
    out = bytearray()
    gaps: list[tuple[int, int]] = []
    prev_end: int | None = None
    for cluster in chain:
        start = fat.cluster_offset(cluster)
        chunk = src.at(start, fat.cluster_size)
        if len(chunk) < fat.cluster_size:
            gaps.append((len(out), len(out) + fat.cluster_size - len(chunk)))
            chunk = chunk + b"\x00" * (fat.cluster_size - len(chunk))
        if prev_end is not None and start != prev_end:
            gaps.append((len(out), max(0, start - prev_end)))
        out += chunk
        prev_end = start + fat.cluster_size
    if size and size < len(out):
        del out[size:]
    return bytes(out), gaps


def _decode_short(raw: bytes) -> str:
    base = raw[:8].decode("ascii", "replace").rstrip()
    ext = raw[8:11].decode("ascii", "replace").rstrip()
    return f"{base}.{ext}" if ext else base


def _lfn_name(slots: list[bytes]) -> str:
    parts: list[str] = []
    for slot in reversed(slots):
        for off, count in ((0x01, 5), (0x0E, 6), (0x1C, 2)):
            chunk = slot[off:off + count * 2]
            for i in range(0, len(chunk), 2):
                code = struct.unpack("<H", chunk[i:i + 2])[0]
                if code in (0x0000, 0xFFFF):
                    return "".join(parts)
                parts.append(chr(code))
    return "".join(parts)


def dos_time(date: int, clock: int) -> float | None:
    """A FAT date/time pair (local time) to a Unix timestamp."""
    if date == 0:
        return None
    year = 1980 + (date >> 9)
    month = (date >> 5) & 0x0F
    day = date & 0x1F
    hour = clock >> 11
    minute = (clock >> 5) & 0x3F
    second = (clock & 0x1F) * 2
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60):
        return None
    try:
        return time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
    except (OverflowError, ValueError):
        return None


@dataclass
class DirEntry:
    offset: int
    deleted: bool
    name: str
    short_name: str
    attr: int
    cluster: int
    size: int
    is_dir: bool
    modified: float | None = None


def parse_dir_entries(raw: bytes) -> list[DirEntry]:
    entries: list[DirEntry] = []
    pending: list[bytes] = []
    pos = 0
    while pos + 32 <= len(raw):
        slot = raw[pos:pos + 32]
        first = slot[0]
        if first == 0x00:
            break
        attr = slot[0x0B]
        if attr == ATTR_LFN:
            pending.append(slot)
            pos += 32
            continue
        if first == DELETED_MARK:
            deleted = True
            display = b"_" + slot[1:11]
        else:
            deleted = False
            display = slot[0:11]
        name = _lfn_name(pending) if pending else ""
        pending = []
        if attr & ATTR_VOLUME:
            pos += 32
            continue
        cluster = struct.unpack_from("<H", slot, 0x14)[0] << 16
        cluster |= struct.unpack_from("<H", slot, 0x1A)[0]
        size = struct.unpack_from("<I", slot, 0x1C)[0]
        modified = dos_time(struct.unpack_from("<H", slot, 0x18)[0],
                            struct.unpack_from("<H", slot, 0x16)[0])
        entries.append(DirEntry(
            offset=pos, deleted=deleted,
            name=name or _decode_short(display),
            short_name=_decode_short(display),
            attr=attr, cluster=cluster, size=size, is_dir=bool(attr & DIR_ATTR),
            modified=modified,
        ))
        pos += 32
    return entries


def read_dir_entries(src, fat: FatInfo, chain: list[int]) -> list[DirEntry]:
    raw, _ = read_clusters(src, fat, chain, 0)
    return parse_dir_entries(raw)


def _sanitise(name: str) -> str:
    cleaned = "".join(c for c in name if c.isprintable() and c not in '\\/:*?"<>|')
    return cleaned.strip() or "unnamed"


def recover_fat(
    src,
    volume: str,
    root_cluster: int | None = None,
    path_prefix: str = "",
    max_depth: int = 32,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    read_data: bool = False,
    include_live: bool = False,
) -> Iterator[FileCandidate]:
    """Walk the whole directory tree and yield every deleted file it still knows.

    ``include_live`` also yields files that were not deleted (lost volumes).

    Live folders are walked as well as deleted ones: a file deleted from a
    folder that still exists is the most common case of all. Candidates carry
    ``metadata["extents"]``; ``read_data`` also fills ``inline_data``.
    """
    fat = find_fat(src)
    if fat is None:
        return
    table = load_table(src, fat)
    seen: set[int] = set()
    if root_cluster:
        entries = read_dir_entries(src, fat, read_chain(src, fat, root_cluster))
    elif fat.bits == 32:
        start = fat.root_cluster or 2
        seen.add(start)
        entries = read_dir_entries(src, fat, read_chain(src, fat, start))
    else:
        entries = parse_dir_entries(src.at(fat.root_dir_offset, fat.root_entries * 32))
    yield from _walk(src, fat, table, entries, path_prefix, False, 0, max_depth,
                     volume, progress, should_stop, read_data, seen, include_live)


def _walk(src, fat: FatInfo, table: list[int], entries: list[DirEntry], prefix: str,
          in_deleted: bool, depth: int, max_depth: int, volume: str, progress,
          should_stop, read_data: bool, seen: set[int],
          include_live: bool = False) -> Iterator[FileCandidate]:
    if depth > max_depth:
        return
    if progress is not None:
        progress(fat.cluster_size)
    for entry in entries:
        if should_stop is not None and should_stop():
            return
        if entry.short_name in (".", "..") or entry.name in (".", ".."):
            continue
        if entry.is_dir:
            if entry.cluster < 2 or entry.cluster in seen:
                continue
            seen.add(entry.cluster)
            if entry.deleted:
                chain, _guessed = deleted_chain(src, fat, entry.cluster,
                                                fat.cluster_size, table)
            else:
                chain = read_chain(src, fat, entry.cluster)
            if not chain:
                continue
            sub = f"{prefix}/{_sanitise(entry.name)}" if prefix else _sanitise(entry.name)
            yield from _walk(src, fat, table, read_dir_entries(src, fat, chain), sub,
                             in_deleted or entry.deleted, depth + 1, max_depth, volume,
                             progress, should_stop, read_data, seen, include_live)
            continue
        if not (entry.deleted or in_deleted or include_live):
            continue
        if entry.cluster < 2 or entry.size == 0:
            continue
        if entry.deleted:
            chain, guessed = deleted_chain(src, fat, entry.cluster, entry.size, table)
        else:
            chain, guessed = read_chain(src, fat, entry.cluster), False
        if not chain:
            continue
        need = max(1, -(-entry.size // fat.cluster_size))
        short = len(chain) < need
        size = min(entry.size, len(chain) * fat.cluster_size)
        name = _sanitise(entry.name)
        path = f"{prefix}/{name}" if prefix else name
        extents = chain_extents(fat, chain, size)
        fragmented = len(extents) > 1
        reasons = ["directory entry marked deleted (0xE5)" if entry.deleted
                   else "inside a deleted folder" if in_deleted else "in use when this volume was lost"]
        reasons.append(f"{len(chain)} cluster(s), long name "
                       f"{'recovered' if entry.name != entry.short_name else 'unavailable'}")
        if guessed:
            reasons.append("chain freed on delete; assumed to continue through the "
                           "next free clusters")
        if short:
            reasons.append(f"only {len(chain)} of {need} clusters found before the "
                           f"end of the volume")
        metadata = {
            "chain": chain,
            "extents": extents,
            "cluster_size": fat.cluster_size,
            "dir_offset": entry.offset,
            "modified": entry.modified,
            "chain_guessed": guessed,
            "folder_deleted": in_deleted,
            "live": not entry.deleted and not in_deleted,
        }
        if read_data:
            metadata["inline_data"], _gaps = read_clusters(src, fat, chain, size)
        yield FileCandidate(
            ext=_extension(name),
            size=size,
            data_offset=-1,
            strategy=Strategy.FAT,
            name=name,
            original_path=path,
            verdict=Verdict.PARTIAL if short else Verdict.VALID,
            confidence=0.55 if short else (0.7 if guessed else 0.8),
            reasons=reasons,
            volume=volume,
            fragment_count=len(extents) if fragmented else 1,
            metadata=metadata,
        )


def _extension(name: str) -> str:
    if "." in name[1:]:
        return name.rsplit(".", 1)[1].lower()[:16]
    return ""
