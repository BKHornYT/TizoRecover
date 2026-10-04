"""exFAT: recover files from deleted directory entry sets.

exFAT keeps each file as an *entry set*: a File entry (attributes, times),
a Stream Extension (first cluster, size, and whether the clusters are one
contiguous run) and one File Name entry per 15 characters. Deleting a file
only clears the top bit of each entry's type byte (0x85 -> 0x05, 0xC0 -> 0x40,
0xC1 -> 0x41) and the file's bits in the allocation bitmap, so the full name,
size, dates and first cluster all survive.

Most files on an exFAT drive are written as one contiguous run ("NoFatChain"),
and for those the location is exact. Fragmented files use the FAT; Windows
and Linux leave those FAT entries in place when deleting, so the chain is
followed when it still checks out, and assumed contiguous (and reported so)
when it does not.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Iterator

from tizorecover.engine.fs.fat import dos_time
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

ENTRY = 32
FILE, STREAM, NAME = 0x05, 0x40, 0x41        # type codes without the in-use bit
IN_USE = 0x80
BITMAP, UPCASE, LABEL = 0x81, 0x82, 0x83
ATTR_DIR = 0x10
FAT_END = 0xFFFFFFF8
FAT_BAD = 0xFFFFFFF7
MAX_DIR_BYTES = 256 << 20


@dataclass
class ExfatInfo:
    bytes_per_sector: int
    cluster_size: int
    fat_offset: int          # bytes
    fat_length: int          # bytes
    heap_offset: int         # bytes
    cluster_count: int
    root_cluster: int
    volume_length: int       # bytes

    def cluster_offset(self, cluster: int) -> int:
        return self.heap_offset + (cluster - 2) * self.cluster_size

    def valid_cluster(self, cluster: int) -> bool:
        return 2 <= cluster < self.cluster_count + 2


def find_exfat(src) -> ExfatInfo | None:
    boot = src.at(0, 512)
    if len(boot) < 512 or boot[3:11] != b"EXFAT   " or boot[510:512] != b"\x55\xaa":
        return None
    bps_shift, spc_shift = boot[108], boot[109]
    if not 9 <= bps_shift <= 12 or bps_shift + spc_shift > 25:
        return None
    bps = 1 << bps_shift
    volume_length, = struct.unpack_from("<Q", boot, 72)
    fat_off, fat_len, heap_off, count, root = struct.unpack_from("<IIIII", boot, 80)
    info = ExfatInfo(bps, bps << spc_shift, fat_off * bps, fat_len * bps, heap_off * bps,
                     count, root, volume_length * bps)
    if not info.valid_cluster(root) or info.fat_offset <= 0 or info.heap_offset <= info.fat_offset:
        return None
    return info


class Fat:
    """The FAT, read lazily in blocks (it can be tens of MB on a big card)."""

    BLOCK = 1 << 20

    def __init__(self, src, info: ExfatInfo) -> None:
        self.src = src
        self.info = info
        self._blocks: dict[int, bytes] = {}

    def __getitem__(self, cluster: int) -> int:
        pos = cluster * 4
        if pos + 4 > self.info.fat_length:
            return 0
        block, rel = divmod(pos, self.BLOCK)
        data = self._blocks.get(block)
        if data is None:
            if len(self._blocks) > 64:
                self._blocks.clear()
            data = self.src.at(self.info.fat_offset + block * self.BLOCK, self.BLOCK)
            self._blocks[block] = data
        if rel + 4 > len(data):
            return 0
        return int.from_bytes(data[rel:rel + 4], "little")


def fat_chain(fat: Fat, start: int, want: int | None = None) -> list[int] | None:
    """Follow the FAT from ``start``; None if it leads anywhere it should not."""
    info = fat.info
    chain = []
    seen = set()
    cluster = start
    limit = want if want is not None else info.cluster_count
    while True:
        if not info.valid_cluster(cluster) or cluster in seen or len(chain) > limit:
            return None
        chain.append(cluster)
        seen.add(cluster)
        nxt = fat[cluster]
        if nxt >= FAT_END:
            return chain
        if nxt == FAT_BAD or nxt == 0:
            return None
        cluster = nxt


def runs_of(info: ExfatInfo, chain: list[int], size: int) -> list[tuple[int, int]]:
    """Volume ``(offset, length)`` extents for a cluster chain, merged where contiguous."""
    out: list[tuple[int, int]] = []
    left = size
    i = 0
    while i < len(chain) and left > 0:
        j = i
        while j + 1 < len(chain) and chain[j + 1] == chain[j] + 1:
            j += 1
        length = min((j - i + 1) * info.cluster_size, left)
        out.append((info.cluster_offset(chain[i]), length))
        left -= length
        i = j + 1
    return out


def _clusters_for(info: ExfatInfo, size: int) -> int:
    return max(1, -(-size // info.cluster_size))


def _set_checksum(entries: bytes) -> int:
    chk = 0
    for i, b in enumerate(entries):
        if i in (2, 3):
            continue
        chk = (((chk & 1) << 15) | (chk >> 1)) + b
        chk &= 0xFFFF
    return chk


def _timestamp(raw: int, centis: int) -> float | None:
    t = dos_time(raw >> 16, raw & 0xFFFF)
    return None if t is None else t + min(centis, 199) / 100.0


@dataclass
class EntrySet:
    deleted: bool
    name: str
    is_dir: bool
    first_cluster: int
    size: int
    contiguous: bool
    modified: float | None
    checksum_ok: bool
    offset: int              # offset of the File entry inside the directory data


def parse_entry_sets(raw: bytes) -> Iterator[EntrySet]:
    """Every File entry set in a directory's bytes, live and deleted."""
    pos = 0
    n = len(raw)
    while pos + ENTRY <= n:
        kind = raw[pos]
        if kind == 0x00:
            # "End of directory" is only a hint: entries after it can be old
            # deleted sets, so keep going while the bytes still look like entries.
            if raw[pos:pos + ENTRY] == bytes(ENTRY):
                pos += ENTRY
                continue
        code = kind & 0x7F
        if code != FILE:
            pos += ENTRY
            continue
        deleted = not (kind & IN_USE)
        count = raw[pos + 1]
        end = pos + ENTRY * (1 + count)
        if not 2 <= count <= 18 or end > n:
            pos += ENTRY
            continue
        stream = raw[pos + ENTRY:pos + 2 * ENTRY]
        if (stream[0] & 0x7F) != STREAM or bool(stream[0] & IN_USE) == deleted:
            pos += ENTRY
            continue
        names = []
        ok = True
        for k in range(2, 1 + count):
            e = raw[pos + k * ENTRY:pos + (k + 1) * ENTRY]
            if (e[0] & 0x7F) == NAME and bool(e[0] & IN_USE) != deleted:
                names.append(e[2:32])
            elif (e[0] & 0x7F) == NAME:
                ok = False
                break
        if not ok or not names:
            pos += ENTRY
            continue
        name_len = stream[3]
        try:
            name = b"".join(names).decode("utf-16-le", "replace")[:name_len]
        except ValueError:
            pos += ENTRY
            continue
        if not name or name_len == 0 or "\x00" in name:
            pos += ENTRY
            continue
        entries = bytearray(raw[pos:end])
        if deleted:
            for k in range(0, len(entries), ENTRY):
                entries[k] |= IN_USE
        stored = struct.unpack_from("<H", raw, pos + 2)[0]
        attrs = struct.unpack_from("<H", raw, pos + 4)[0]
        modified_raw = struct.unpack_from("<I", raw, pos + 12)[0]
        first = struct.unpack_from("<I", stream, 20)[0]
        size = struct.unpack_from("<Q", stream, 24)[0]
        yield EntrySet(
            deleted=deleted, name=name, is_dir=bool(attrs & ATTR_DIR), first_cluster=first,
            size=size, contiguous=bool(stream[1] & 0x02),
            modified=_timestamp(modified_raw, raw[pos + 21]),
            checksum_ok=_set_checksum(bytes(entries)) == stored, offset=pos,
        )
        pos = end


def read_directory(src, info: ExfatInfo, fat: Fat, first: int, size: int | None,
                   contiguous: bool) -> bytes:
    if not info.valid_cluster(first):
        return b""
    if contiguous and size:
        return src.at(info.cluster_offset(first), min(size, MAX_DIR_BYTES))
    chain = fat_chain(fat, first)
    if not chain:
        # A deleted folder whose chain is gone: its first cluster is all we know.
        chain = [first]
    out = bytearray()
    for start, length in runs_of(info, chain, len(chain) * info.cluster_size):
        out += src.at(start, length)
        if len(out) > MAX_DIR_BYTES:
            break
    return bytes(out)


def _sanitise(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip() or "_"


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[1].lower()[:16] if "." in name[1:] else ""


def bitmap_location(src, info: ExfatInfo, fat: Fat) -> tuple[int, int] | None:
    """(first cluster, length) of the allocation bitmap, from the root directory."""
    raw = read_directory(src, info, fat, info.root_cluster, None, False)
    for pos in range(0, len(raw) - ENTRY + 1, ENTRY):
        if raw[pos] == BITMAP and not raw[pos + 1] & 1:          # first bitmap (TexFAT has two)
            first, length = struct.unpack_from("<IQ", raw, pos + 20)
            return first, length
        if raw[pos] == 0x00 and raw[pos:pos + ENTRY] == bytes(ENTRY):
            break
    return None


def load_bitmap(src, info: ExfatInfo, fat: Fat | None = None) -> bytes:
    fat = fat or Fat(src, info)
    where = bitmap_location(src, info, fat)
    if where is None:
        return b""
    first, length = where
    if not info.valid_cluster(first):
        return b""
    return src.at(info.cluster_offset(first), min(length, (info.cluster_count + 7) // 8))


def recover_exfat(
    src,
    volume: str,
    max_depth: int = 32,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    include_live: bool = False,
) -> Iterator[FileCandidate]:
    """Walk the whole tree (live and deleted folders) and yield every deleted file.

    ``include_live`` also yields files that were not deleted (lost volumes).
    """
    info = find_exfat(src)
    if info is None:
        return
    fat = Fat(src, info)
    bitmap = load_bitmap(src, info, fat)
    root = read_directory(src, info, fat, info.root_cluster, None, False)
    seen = {info.root_cluster}
    yield from _walk(src, info, fat, bitmap, root, "", False, 0, max_depth, volume, progress,
                     should_stop, seen, include_live)


def _in_use(bitmap: bytes, cluster: int) -> bool:
    i = cluster - 2
    return 0 <= i // 8 < len(bitmap) and bool(bitmap[i // 8] >> (i % 8) & 1)


def free_run_guess(info: ExfatInfo, bitmap: bytes, first: int, need: int) -> list[int]:
    """The usual undelete guess: the file went on through the next free clusters.

    A fragmented file was fragmented because other files sat in the way, and
    those are usually still there, so clusters in use now are skipped.
    """
    chain = [first]
    cluster = first + 1
    while len(chain) < need and info.valid_cluster(cluster):
        if not _in_use(bitmap, cluster):
            chain.append(cluster)
        cluster += 1
    return chain


def _walk(src, info: ExfatInfo, fat: Fat, bitmap: bytes, raw: bytes, prefix: str, in_deleted: bool, depth: int,
          max_depth: int, volume: str, progress, should_stop, seen: set[int],
          include_live: bool = False) -> Iterator[FileCandidate]:
    if depth > max_depth:
        return
    if progress is not None:
        progress(len(raw))
    for es in parse_entry_sets(raw):
        if should_stop is not None and should_stop():
            return
        name = _sanitise(es.name)
        path = f"{prefix}/{name}" if prefix else name
        if es.is_dir:
            if not info.valid_cluster(es.first_cluster) or es.first_cluster in seen:
                continue
            seen.add(es.first_cluster)
            sub = read_directory(src, info, fat, es.first_cluster, es.size, es.contiguous)
            yield from _walk(src, info, fat, bitmap, sub, path, in_deleted or es.deleted, depth + 1,
                             max_depth, volume, progress, should_stop, seen, include_live)
            continue
        if not (es.deleted or in_deleted or include_live) or es.size == 0 or not info.valid_cluster(es.first_cluster):
            continue
        need = _clusters_for(info, es.size)
        guessed = False
        if es.contiguous:
            chain = list(range(es.first_cluster, es.first_cluster + need))
            how = "one contiguous run (exact)"
        else:
            chain = fat_chain(fat, es.first_cluster, need)
            if chain is not None and len(chain) == need:
                how = f"cluster chain still in the FAT ({len(chain)} clusters)"
            else:
                chain = free_run_guess(info, bitmap, es.first_cluster, need)
                guessed = True
                how = "cluster chain gone; assumed to go on through the next free clusters"
        last_ok = chain[-1] < info.cluster_count + 2
        if not last_ok:
            chain = [c for c in chain if info.valid_cluster(c)]
        size = min(es.size, len(chain) * info.cluster_size)
        extents = runs_of(info, chain, size)
        reasons = ["entry set marked deleted" if es.deleted else "inside a deleted folder" if in_deleted
                   else "in use when this volume was lost", how]
        if es.checksum_ok:
            reasons.append("entry set checksum matches")
        yield FileCandidate(
            ext=_extension(name), size=size, data_offset=-1, strategy=Strategy.EXFAT,
            name=name, original_path=path,
            verdict=Verdict.VALID if last_ok else Verdict.PARTIAL,
            confidence=0.85 if not guessed else 0.65,
            reasons=reasons, volume=volume,
            fragment_count=len(extents),
            metadata={"extents": extents, "cluster_size": info.cluster_size,
                      "modified": es.modified, "chain_guessed": guessed,
                      "folder_deleted": in_deleted, "first_cluster": es.first_cluster,
                      "live": not es.deleted and not in_deleted},
        )
