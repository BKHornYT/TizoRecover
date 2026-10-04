"""NTFS: recover deleted files from the $MFT.

NTFS keeps the master file table on the volume itself, and an unlinked
file's record is usually still there with its name, its timestamps and its
data runs, marked no longer in use. That makes NTFS the friendliest
filesystem to recover from, and the only one where the original folder can
usually be recovered too.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Iterator

from tizorecover.engine.results import FileCandidate, Strategy, Verdict

MFT_RECORD = b"FILE"
ATTR_STANDARD_INFORMATION = 0x10
ATTR_ATTRIBUTE_LIST = 0x20
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_INDEX_ALLOCATION = 0xA0
_FT_MIN = 119600064000000000      # 1980-01-01 as a FILETIME
_FT_MAX = 157469184000000000      # 2100-01-01
FLAG_IN_USE = 0x0001
FLAG_DIRECTORY = 0x0002
SYSTEM_EXTENTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
SPARSE = -1
BITMAP_RECORD = 6
FILETIME_EPOCH = 116444736000000000


@dataclass
class BootSector:
    bytes_per_sector: int
    sectors_per_cluster: int
    total_sectors: int
    mft_lcn: int
    mft_record_size: int
    mftmirr_lcn: int
    index_record_size: int
    serial: int

    @property
    def cluster_size(self) -> int:
        return self.bytes_per_sector * self.sectors_per_cluster

    def offset(self, cluster: int) -> int:
        return cluster * self.cluster_size


def _s8(data: bytes, off: int) -> int:
    return struct.unpack_from("<b", data, off)[0]


def _s16(data: bytes, off: int) -> int:
    return struct.unpack_from("<h", data, off)[0]


def parse_boot_sector(src) -> BootSector | None:
    head = src.at(0, 512)
    if len(head) < 512 or head[3:11] != b"NTFS    ":
        return None
    bps = struct.unpack_from("<H", head, 0x0B)[0]
    spc = head[0x0D]
    if bps not in (512, 1024, 2048, 4096) or not 1 <= spc <= 128:
        return None
    if head[510:512] != b"\x55\xaa":
        return None
    cluster_size = bps * spc
    total = struct.unpack_from("<Q", head, 0x28)[0]
    mft_lcn = struct.unpack_from("<Q", head, 0x30)[0]
    mftmirr_lcn = struct.unpack_from("<Q", head, 0x38)[0]
    per_record = _s8(head, 0x40)
    mft_record = (1 << -per_record) if per_record < 0 else per_record * cluster_size
    per_index = _s16(head, 0x42)
    index_size = (1 << -per_index) if per_index < 0 else per_index * cluster_size
    if not 256 <= mft_record <= 65536 or mft_record & (mft_record - 1):
        return None
    if not 256 <= index_size <= 65536:
        index_size = 4096
    return BootSector(bps, spc, total or 0, mft_lcn, mft_record, mftmirr_lcn,
                      index_size, struct.unpack_from("<I", head, 0x44)[0])


def apply_fixups(record: bytearray, sector_size: int) -> bool:
    """Undo the update-sequence array so a record's fields can be trusted."""
    usa_ofs, usa_count = struct.unpack_from("<HH", record, 4)
    if usa_count == 0 or usa_ofs + usa_count * 2 > len(record):
        return False
    usn = record[usa_ofs:usa_ofs + 2]
    for i in range(1, usa_count):
        end = i * sector_size - 2
        if end + 2 > len(record):
            return False
        if bytes(record[end:end + 2]) != usn:
            return False
        saved = record[usa_ofs + i * 2: usa_ofs + i * 2 + 2]
        record[end:end + 2] = saved
    return True


@dataclass
class Attribute:
    type: int
    resident: bool
    value: bytes = b""
    runs: list[tuple[int, int, int]] = field(default_factory=list)
    real_size: int = 0
    allocated_size: int = 0
    start_vcn: int = 0
    last_vcn: int = -1
    compressed: bool = False
    sparse: bool = False
    name: str = ""
    length: int = 0


def follow_attribute_list(src, boot: BootSector, mft_lcn: int, index: int,
                          record: bytes, mft_map: "MftMap | None" = None,
                          depth: int = 0) -> list[Attribute]:
    """Collect the attributes an ``$ATTRIBUTE_LIST`` points at.

    A record whose attributes do not fit in 1 KiB -- ``$UsnJrnl`` is the
    standard example, because its ``$J`` runlist is enormous -- keeps only a
    stub in the base record and lists where the rest really live. Reading such
    a record without following the list yields a name and nothing else, which
    is how the USN journal ends up looking absent when it is right there.
    """
    if depth > 4:
        return []
    stub = next((a for a in parse_attributes(record)
                 if a.type == ATTR_ATTRIBUTE_LIST), None)
    if stub is None:
        return []
    if stub.resident:
        blob = stub.value
    else:
        blob, _gaps = read_attribute_runs(src, boot, stub.runs, stub.real_size)

    found: list[Attribute] = []
    pos = 0
    while pos + 26 <= len(blob):
        atype, alen, name_len, name_off = struct.unpack_from("<IHBB", blob, pos)
        start_vcn = struct.unpack_from("<Q", blob, pos + 8)[0]
        reference = struct.unpack_from("<Q", blob, pos + 16)[0]
        if alen < 26:
            break
        target = reference & 0x0000FFFFFFFFFFFF
        if name_len and name_off:
            want = blob[pos + name_off: pos + name_off + name_len * 2].decode(
                "utf-16-le", "replace")
        else:
            want = ""
        pos += alen

        if mft_map is not None:
            offset = mft_map.offset_of(target)
        else:
            offset = mft_lcn * boot.cluster_size + target * boot.mft_record_size
        if offset is None:
            continue
        raw = src.at(offset, boot.mft_record_size)
        if len(raw) < 0x30 or raw[:4] != MFT_RECORD:
            continue
        fixed = bytearray(raw)
        if not apply_fixups(fixed, boot.bytes_per_sector):
            continue
        # The entry names the attribute but not where it sits in the target
        # record, so match on type, name and starting VCN instead.
        for attr in parse_attributes(bytes(fixed)):
            if (attr.type == atype and attr.name == want
                    and attr.start_vcn == start_vcn):
                found.append(attr)
                break

    return found


def parse_attributes(record: bytes) -> list[Attribute]:
    if len(record) < 0x18:
        return []
    first = struct.unpack_from("<H", record, 0x14)[0]
    used = struct.unpack_from("<I", record, 0x18)[0]
    end = min(used if used else len(record), len(record))
    attrs: list[Attribute] = []
    pos = first
    while pos + 8 <= end:
        attr = parse_attribute_at(record, pos)
        if attr is None:
            break
        attrs.append(attr)
        pos += attr.length
    return attrs


def parse_attribute_at(record: bytes, pos: int) -> Attribute | None:
    """Decode the single attribute header that starts at ``pos``.

    An ``$ATTRIBUTE_LIST`` entry points straight at an attribute inside another
    MFT record, so this has to be usable at an arbitrary offset rather than
    only while walking a record from its first attribute.
    """
    if pos + 16 > len(record):
        return None
    atype = struct.unpack_from("<I", record, pos)[0]
    if atype == 0xFFFFFFFF:
        return None
    alen = struct.unpack_from("<I", record, pos + 4)[0]
    if alen < 16 or pos + alen > len(record):
        return None
    non_resident = record[pos + 8] != 0
    name_len = record[pos + 9]
    name_off = struct.unpack_from("<H", record, pos + 0x0A)[0]
    attr_flags = struct.unpack_from("<H", record, pos + 0x0C)[0]
    attr = Attribute(type=atype, resident=not non_resident,
                     compressed=bool(attr_flags & 0x0001))
    attr.length = alen
    if name_len:
        raw = record[pos + name_off: pos + name_off + name_len * 2]     # length is in characters
        attr.name = raw.decode("utf-16-le", "replace")
    if not non_resident:
        vlen = struct.unpack_from("<I", record, pos + 0x10)[0]
        voff = struct.unpack_from("<H", record, pos + 0x14)[0]
        attr.value = record[pos + voff: pos + voff + vlen]
        attr.real_size = vlen
        attr.allocated_size = vlen
    else:
        attr.start_vcn = struct.unpack_from("<Q", record, pos + 0x10)[0]
        attr.last_vcn = struct.unpack_from("<q", record, pos + 0x18)[0]
        run_off = struct.unpack_from("<H", record, pos + 0x20)[0]
        attr.allocated_size = struct.unpack_from("<Q", record, pos + 0x28)[0]
        attr.real_size = struct.unpack_from("<Q", record, pos + 0x30)[0]
        attr.sparse = bool(attr_flags & 0x8000)
        attr.runs = parse_runs(record[pos + run_off: pos + alen])
    return attr


def parse_runs(blob: bytes) -> list[tuple[int, int, int]]:
    """Decode a data runlist into ``(vcn, lcn, cluster_count)`` triples."""
    runs: list[tuple[int, int, int]] = []
    pos = 0
    lcn = 0
    vcn = 0
    while pos < len(blob):
        header = blob[pos]
        if header == 0:
            break
        len_size = header & 0x0F
        off_size = (header >> 4) & 0x0F
        pos += 1
        if len_size == 0 or pos + len_size + off_size > len(blob):
            break
        length = int.from_bytes(blob[pos:pos + len_size], "little", signed=False)
        pos += len_size
        if off_size:
            delta = int.from_bytes(blob[pos:pos + off_size], "little", signed=True)
            pos += off_size
            lcn += delta
            runs.append((vcn, lcn, length))
        else:
            runs.append((vcn, SPARSE, length))
        vcn += length
    return runs


@dataclass
class MftEntry:
    index: int
    in_use: bool
    is_dir: bool
    base_index: int
    sequence: int
    attributes: list[Attribute]

    def first(self, atype: int) -> Attribute | None:
        for a in self.attributes:
            if a.type == atype:
                return a
        return None

    def all_of(self, atype: int) -> list[Attribute]:
        return [a for a in self.attributes if a.type == atype]

    def names(self) -> list[tuple[int, str, int, int]]:
        """``(parent_index, name, namespace, size)`` for every $FILE_NAME."""
        # $FILE_NAME: parent ref 0x00, four times 0x08-0x27, allocated and real
        # size 0x28/0x30, flags 0x38, reparse value 0x3C, then the name length
        # (in characters) at 0x40, the namespace at 0x41 and the name at 0x42.
        out = []
        for a in self.all_of(ATTR_FILE_NAME):
            if len(a.value) < 0x42:
                continue
            reference = struct.unpack_from("<Q", a.value, 0)[0]
            parent_index = reference & 0x0000FFFFFFFFFFFF
            real = struct.unpack_from("<Q", a.value, 0x30)[0]
            nlen = a.value[0x40]
            namespace = a.value[0x41]
            raw = a.value[0x42: 0x42 + nlen * 2]
            name = raw.decode("utf-16-le", "replace")
            if name in (".", ".."):
                continue
            out.append((parent_index, name, namespace, real))
        return out


class MftMap:
    """Where MFT records physically live.

    The $MFT is an ordinary fragmented file, not one long run of clusters. On a
    real volume it is typically a dozen extents scattered right across the
    disk, and its first extent holds only a fraction of the records. Reading
    ``$MFT start + index * record_size`` therefore walks off the end of the
    first extent and into whatever else is on the volume, which is why this
    maps an index through the runlist that record 0 carries.
    """

    def __init__(self, boot: BootSector, runs: list[tuple[int, int, int]],
                 record_count: int) -> None:
        self.boot = boot
        self.runs = runs
        self.record_count = record_count
        self.records_per_cluster = max(1, boot.cluster_size // boot.mft_record_size)

    @classmethod
    def locate(cls, src, boot: BootSector, mft_lcn: int) -> "MftMap | None":
        """Read $MFT record 0 and take its extents and real record count."""
        entry = read_mft_entry(src, boot, mft_lcn, 0)
        if entry is None:
            return None
        data = entry.first(ATTR_DATA)
        if data is None or data.resident or not data.runs:
            return None
        records_per_cluster = max(1, boot.cluster_size // boot.mft_record_size)
        capacity = sum(c for _v, _l, c in data.runs) * records_per_cluster
        header = src.at(mft_lcn * boot.cluster_size, boot.mft_record_size)
        count = 0
        if len(header) >= 0x48 and header[:4] == MFT_RECORD:
            # Record 0's own header carries the $MFT's allocated/real/initialized
            # sizes at 0x30/0x38/0x40. The initialized size is the record count;
            # 0x38 is the byte length, which is not it. Anything outside the
            # extents' own capacity is not a record count, so ignore it.
            claimed = struct.unpack_from("<Q", header, 0x40)[0]
            if 0 < claimed <= capacity:
                count = claimed
        return cls(boot, data.runs, count or capacity)

    def offset_of(self, index: int) -> int | None:
        """Byte offset of record ``index``, or None when it is past the end."""
        if index < 0 or index >= self.record_count:
            return None
        cluster_in_file = index // self.records_per_cluster
        for vcn, lcn, count in self.runs:
            if vcn <= cluster_in_file < vcn + count:
                cluster = lcn + cluster_in_file - vcn
                return (cluster * self.boot.cluster_size
                        + (index % self.records_per_cluster) * self.boot.mft_record_size)
        return None

    def __len__(self) -> int:
        return self.record_count

    def contiguous_span(self, index: int, count: int) -> tuple[int, int] | None:
        """Byte offset and length of ``count`` records from ``index``.

        None when the range is out of bounds or would cross an extent
        boundary, where the records are not adjacent on disk and a single
        read would pick up the wrong bytes.
        """
        if count <= 0 or index < 0 or index + count > self.record_count:
            return None
        first = self.offset_of(index)
        last = self.offset_of(index + count - 1)
        if first is None or last is None:
            return None
        span = last + self.boot.mft_record_size - first
        if span == count * self.boot.mft_record_size:
            return first, span
        return None


def read_mft_entry(src, boot: BootSector, mft_lcn: int, index: int,
                   mft_map: "MftMap | None" = None) -> MftEntry | None:
    """Read one MFT record by index.

    ``mft_map`` follows the $MFT's own extents. Without it the record is
    assumed to sit at ``$MFT start + index * record_size``, which only holds
    while the $MFT is one contiguous run.
    """
    if mft_map is not None:
        offset = mft_map.offset_of(index)
        if offset is None:
            return None
    else:
        offset = mft_lcn * boot.cluster_size + index * boot.mft_record_size
    raw = src.at(offset, boot.mft_record_size)
    return parse_mft_record(raw, boot, index)


def parse_mft_record(raw: bytes, boot: BootSector, index: int) -> MftEntry | None:
    """Turn one raw MFT record into an entry, or None when it is not one."""
    if len(raw) < 0x30 or raw[:4] != MFT_RECORD:
        return None
    record = bytearray(raw)
    if not apply_fixups(record, boot.bytes_per_sector):
        return None
    flags = struct.unpack_from("<H", record, 0x16)[0]
    base_ref = struct.unpack_from("<Q", record, 0x20)[0]
    return MftEntry(
        index=index,
        in_use=bool(flags & FLAG_IN_USE),
        is_dir=bool(flags & FLAG_DIRECTORY),
        base_index=base_ref & 0x0000FFFFFFFFFFFF,
        sequence=struct.unpack_from("<H", bytes(record), 0x10)[0],
        attributes=parse_attributes(bytes(record)),
    )


def iter_mft_entries(src, boot: BootSector, mft_lcn: int, total: int,
                     mft_map: "MftMap | None" = None,
                     batch: int = 128) -> Iterator[MftEntry | None]:
    """Walk MFT records 0..total-1, reading neighbours in one go.

    Records are 1 KiB each and a whole extent is adjacent on disk, so reading
    one record at a time costs far more in call overhead than in I/O. Batches
    are used only where the records really are contiguous; ranges that would
    cross an extent boundary fall back to single reads.
    """
    index = 0
    while index < total:
        span = mft_map.contiguous_span(index, batch) if mft_map is not None else None
        if span is not None:
            offset, length = span
            raw = src.at(offset, length)
            for step in range(batch):
                piece = raw[step * boot.mft_record_size:
                            (step + 1) * boot.mft_record_size]
                yield parse_mft_record(piece, boot, index + step)
            index += batch
            continue
        entry = read_mft_entry(src, boot, mft_lcn, index, mft_map)
        yield entry
        index += 1


def find_mft_start(src, boot: BootSector) -> int | None:
    """Locate the $MFT: the boot sector names it, else scan for its records."""
    if boot.mft_lcn and src.at(boot.mft_lcn * boot.cluster_size, 4) == MFT_RECORD:
        return boot.mft_lcn
    clusters = max(0, src.size // boot.cluster_size)
    for cluster in range(min(clusters, 65536)):
        if src.at(cluster * boot.cluster_size, 4) != MFT_RECORD:
            continue
        if src.at(cluster * boot.cluster_size + boot.mft_record_size, 4) == MFT_RECORD:
            return cluster
    return None


def read_attribute_runs(src, boot: BootSector, runs: list[tuple[int, int, int]],
                        real_size: int) -> tuple[bytes, list[tuple[int, int]]]:
    """Reassemble data from a runlist, reporting holes as gaps."""
    out = bytearray()
    gaps: list[tuple[int, int]] = []
    for _vcn, lcn, count in runs:
        want = count * boot.cluster_size
        if lcn == SPARSE:
            out += b"\x00" * want
            continue
        chunk = src.at(boot.offset(lcn), want)
        if len(chunk) < want:
            gaps.append((len(out), len(out) + want - len(chunk)))
            chunk = chunk + b"\x00" * (want - len(chunk))
        out += chunk
    if real_size and real_size < len(out):
        del out[real_size:]
    return bytes(out), gaps


def _fold(names: list[str]) -> str:
    parts = [n for n in names if n]
    return "/".join(parts)


def _folder_needle(want_folder: str | None) -> str | None:
    """Normalise a wanted folder to something comparable with an MFT path.

    MFT paths are built with ``/`` and no drive letter, and a user picks a
    Windows path, so both sides are lowercased, backslashes folded to forward
    slashes and the drive letter dropped.
    """
    if not want_folder:
        return None
    text = str(want_folder).replace("\\", "/").lower()
    if len(text) > 1 and text[1] == ":":
        text = text[2:]
    return text.strip("/") or None


def runs_to_extents(runs: list[tuple[int, int, int]], cluster_size: int,
                    real_size: int) -> list[tuple[int, int]]:
    """``(byte_offset, length)`` pieces covering exactly ``real_size`` bytes.

    A sparse run has no clusters behind it and reads as zeros, so it is
    reported with offset ``-1``. Adjacent runs are merged into one piece.
    """
    out: list[tuple[int, int]] = []
    remaining = real_size
    for _vcn, lcn, count in runs:
        if remaining <= 0:
            break
        length = min(count * cluster_size, remaining)
        offset = SPARSE if lcn == SPARSE else lcn * cluster_size
        if out and offset == SPARSE and out[-1][0] == SPARSE:
            out[-1] = (SPARSE, out[-1][1] + length)
        elif (out and offset != SPARSE and out[-1][0] != SPARSE
              and out[-1][0] + out[-1][1] == offset):
            out[-1] = (out[-1][0], out[-1][1] + length)
        else:
            out.append((offset, length))
        remaining -= length
    return out


def filetime_to_unix(value: int) -> float | None:
    """NTFS FILETIME (100 ns since 1601) to a Unix timestamp."""
    if value <= FILETIME_EPOCH:
        return None
    return (value - FILETIME_EPOCH) / 10_000_000


def _modified_time(entry: "MftEntry") -> float | None:
    info = entry.first(ATTR_STANDARD_INFORMATION)
    if info is None or len(info.value) < 0x10:
        return None
    return filetime_to_unix(struct.unpack_from("<Q", info.value, 0x08)[0])


def load_bitmap(src, boot: BootSector, mft_lcn: int,
                mft_map: "MftMap | None" = None) -> bytes | None:
    """The volume's ``$Bitmap``: one bit per cluster, set while in use."""
    entry = read_mft_entry(src, boot, mft_lcn, BITMAP_RECORD, mft_map)
    if entry is None:
        return None
    data = entry.first(ATTR_DATA)
    if data is None:
        return None
    if data.resident:
        return data.value
    blob, _gaps = read_attribute_runs(src, boot, data.runs, data.real_size)
    return blob or None


def _resolve_path(index: int, dirs: dict[int, tuple[int, str, bool]]) -> tuple[str, bool]:
    """Full path of folder ``index`` and whether any folder on it is deleted."""
    parts: list[str] = []
    seen: set[int] = set()
    deleted = False
    while index != 5 and index not in seen:
        seen.add(index)
        node = dirs.get(index)
        if node is None:
            parts.append(f"$Orphan_{index}")
            deleted = True
            break
        parent, name, in_use = node
        parts.append(name)
        deleted = deleted or not in_use
        index = parent
    return _fold(list(reversed(parts))), deleted


def recover_ntfs(
    src,
    volume: str,
    want_folder: str | None = None,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_entries: int | None = None,
    read_data: bool = False,
    include_live: bool = False,
    ghosts: list | None = None,
) -> Iterator[FileCandidate]:
    """Walk the $MFT and yield every deleted file still described in it.

    ``include_live`` also yields files that were still in use: on a lost or
    formatted-over volume every file it held is one the user wants back.

    Candidates carry ``metadata["extents"]`` -- where the bytes sit on the
    volume -- rather than the bytes themselves, so a scan over a disk full of
    deleted video costs a table walk, not a full read. Resident data (small
    files kept inside the record) is carried inline. ``read_data`` also fills
    ``inline_data`` for non-resident files, for callers that want the bytes.

    Paths are resolved after the whole table has been walked, because a
    folder's record can come after the records of the files inside it.
    """
    boot = parse_boot_sector(src)
    if boot is None:
        return
    mft_lcn = find_mft_start(src, boot)
    if mft_lcn is None:
        return
    mft_map = MftMap.locate(src, boot, mft_lcn)
    needle = _folder_needle(want_folder)
    total_records = len(mft_map) if mft_map else max(1, src.size // max(1, boot.mft_record_size))
    if max_entries is not None:
        total_records = min(total_records, max_entries)
    dirs: dict[int, tuple[int, str, bool]] = {}
    dir_entries: list[MftEntry] = []
    records: dict[int, tuple[int, bool]] = {}          # index -> (sequence, in use)
    found: list[tuple[int, MftEntry, int, str, Attribute]] = []
    for index, entry in enumerate(
            iter_mft_entries(src, boot, mft_lcn, total_records, mft_map)):
        if should_stop is not None and should_stop():
            return
        if progress is not None and index % 512 == 0 and index:
            progress(512 * boot.mft_record_size)
        if entry is None:
            continue
        records[index] = (entry.sequence, entry.in_use)
        if ghosts is not None and entry.is_dir and entry.base_index in (0, index) and \
                (index == 5 or index not in SYSTEM_EXTENTS):
            dir_entries.append(entry)
        if entry.base_index not in (0, index) or index in SYSTEM_EXTENTS:
            continue
        names = entry.names()
        if not names:
            continue
        best = min(names, key=lambda n: n[2] == 2)
        parent_index, name, _ns, _real = best
        if entry.is_dir:
            dirs[entry.index] = (parent_index, name, entry.in_use)
            continue
        if entry.in_use and not include_live:
            continue
        data = entry.first(ATTR_DATA)
        if data is None:
            continue
        found.append((index, entry, parent_index, name, data))

    if ghosts is not None:
        for d in dir_entries:
            if should_stop is not None and should_stop():
                return
            folder = "" if d.index == 5 else _resolve_path(d.index, dirs)[0]
            for g in index_slack_entries(src, boot, d):
                seq, in_use = records.get(g["ref_index"], (-1, False))
                if seq == g["ref_seq"] and not in_use:
                    continue                    # its MFT record is intact: the walk below finds it
                g["path"] = _fold([folder, g["name"]])
                ghosts.append(g)

    for index, entry, parent_index, name, data in found:
        if should_stop is not None and should_stop():
            return
        parent_path, folder_deleted = _resolve_path(parent_index, dirs)
        path = _fold([parent_path, name])
        if needle is not None and needle not in path.lower():
            continue
        metadata = {
            "mft_index": index,
            "parent_index": parent_index,
            "resident": data.resident,
            "compressed": data.compressed,
            "sparse": data.sparse,
            "cluster_size": boot.cluster_size,
            "modified": _modified_time(entry),
            "folder_deleted": folder_deleted,
        }
        if data.resident:
            payload = data.value
            if not payload:
                continue
            size = len(payload)
            metadata["inline_data"] = payload
        else:
            size = data.real_size
            if size <= 0:
                continue
            metadata["runlist"] = [(v, l, c) for v, l, c in data.runs]
            metadata["extents"] = runs_to_extents(data.runs, boot.cluster_size, size)
            if read_data:
                payload, _gaps = read_attribute_runs(src, boot, data.runs, size)
                metadata["inline_data"] = payload
        cand = FileCandidate(
            ext=_extension(name),
            size=size,
            data_offset=-1,
            strategy=Strategy.NTFS,
            name=name,
            original_path=path,
            verdict=Verdict.PARTIAL if data.compressed else Verdict.VALID,
            confidence=0.9 if data.resident else 0.85,
            reasons=[
                f"MFT record {index} in use when this volume was lost" if entry.in_use
                else f"MFT record {index} not in use (sequence {entry.sequence})",
                "resident data in the record itself" if data.resident
                else f"{len(data.runs)} data run(s) in the record",
            ],
            volume=volume,
            metadata=metadata,
        )
        if data.compressed:
            cand.reasons.append("NTFS-compressed: the raw clusters are not the file's bytes")
        if not data.resident and len(data.runs) > 1:
            cand.gaps = _inter_run_gaps(data.runs, boot.cluster_size, size)
            cand.fragment_count = len(data.runs)
            cand.reasons.append(f"split across {len(data.runs)} extents")
        yield cand


def _i30_entry(buf: bytes, pos: int, dir_index: int) -> dict | None:
    """A plausible $I30 index entry at ``pos`` whose parent is ``dir_index``, else None."""
    if pos + 0x52 > len(buf):
        return None
    key_len = struct.unpack_from("<H", buf, pos + 10)[0]
    fn = pos + 0x10
    nlen, namespace = buf[fn + 0x40], buf[fn + 0x41]
    # Deleting the last entry of a block writes the 16-byte end marker over that entry's
    # header (key length 0), but its $FILE_NAME key behind it survives: judge by the key then.
    if nlen == 0 or namespace > 3 or (key_len and not 0x42 + 2 * nlen <= key_len <= 0x42 + 2 * 255 + 8):
        return None
    if fn + 0x42 + 2 * nlen > len(buf):
        return None
    parent = struct.unpack_from("<Q", buf, fn)[0] & 0x0000FFFFFFFFFFFF
    if parent != dir_index:
        return None
    created, modified = struct.unpack_from("<QQ", buf, fn + 0x08)
    if not (_FT_MIN <= modified <= _FT_MAX and _FT_MIN <= created <= _FT_MAX):
        return None
    alloc, real = struct.unpack_from("<QQ", buf, fn + 0x28)
    flags = struct.unpack_from("<I", buf, fn + 0x38)[0]
    if real > alloc or real > 1 << 42 or flags & 0x10000000:          # a folder, not a file
        return None
    try:
        name = buf[fn + 0x42:fn + 0x42 + 2 * nlen].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if any(ord(ch) < 32 for ch in name) or name in (".", ".."):
        return None
    ref = struct.unpack_from("<Q", buf, pos)[0] if key_len else 0
    return {"name": name, "size": real, "modified": filetime_to_unix(modified), "namespace": namespace,
            "ref_index": ref & 0x0000FFFFFFFFFFFF, "ref_seq": ref >> 48, "ext": _extension(name)}


def index_slack_entries(src, boot: BootSector, entry: MftEntry) -> list[dict]:
    """Files a folder's index still remembers in its unused tail (the "slack").

    A folder's $I30 index keeps its file names in 4 KB INDX blocks. Deleting a file
    removes its entry, but the bytes past the block's new end are not cleared: entries
    deleted from the end of a block, and stale copies of shifted ones, stay readable
    there -- name, size and times -- long after the file's MFT record has been reused
    for something else. Short (8.3) duplicates are dropped when a long name exists.
    """
    alloc = next((a for a in entry.all_of(ATTR_INDEX_ALLOCATION) if a.name in ("$I30", "")), None)
    if alloc is None or alloc.resident or not alloc.runs:
        return []
    root = entry.first(ATTR_INDEX_ROOT)
    block = boot.index_record_size or 4096
    if root is not None and len(root.value) >= 12:
        block = struct.unpack_from("<I", root.value, 8)[0] or block
    if not 512 <= block <= 65536:
        return []
    size = alloc.real_size or alloc.allocated_size
    if size <= 0 or size > 64 << 20:
        return []
    data, _gaps = read_attribute_runs(src, boot, alloc.runs, size)
    live: set[str] = set()
    found: dict[tuple[str, int], dict] = {}
    if root is not None and len(root.value) >= 0x20:
        # The root (inside the folder's record) holds live entries too: the B-tree's separators.
        rbuf = bytes(root.value)
        pos = 0x10 + struct.unpack_from("<I", rbuf, 0x10)[0]
        end = 0x10 + struct.unpack_from("<I", rbuf, 0x14)[0]
        while 0x10 <= pos < min(end, len(rbuf)) - 0x10:
            if struct.unpack_from("<I", rbuf, pos + 12)[0] & 0x02:     # the end marker: no key of its own
                break
            e = _i30_entry(rbuf, pos, entry.index)
            if e is not None:
                live.add(e["name"].lower())
            elen = struct.unpack_from("<H", rbuf, pos + 8)[0]
            if elen < 0x10:
                break
            pos += elen
    for start in range(0, len(data) - block + 1, block):
        node = bytearray(data[start:start + block])
        if node[:4] != b"INDX" or not apply_fixups(node, boot.bytes_per_sector):
            continue
        entries_off, used, allocated = struct.unpack_from("<III", node, 0x18)
        first, end_used, end_alloc = 0x18 + entries_off, 0x18 + used, min(block, 0x18 + allocated)
        pos = first
        tail = end_used - (end_used % 8)
        while first <= pos < end_used and pos + 16 <= len(node):   # the live entries: names in use here
            elen = struct.unpack_from("<H", node, pos + 8)[0]
            if struct.unpack_from("<I", node, pos + 12)[0] & 0x02:
                tail = pos        # the end marker; a deleted entry's name can sit right behind it
                break
            e = _i30_entry(bytes(node), pos, entry.index)
            if e is not None:
                live.add(e["name"].lower())
            if elen < 0x10:
                break
            pos += elen
        for pos in range(tail, end_alloc - 0x52, 8):
            e = _i30_entry(bytes(node), pos, entry.index)
            if e is not None:
                found.setdefault((e["name"].lower(), e["size"]), e)
    out = [e for (low, _size), e in found.items() if low not in live]
    longs = {(e["ref_index"], e["ref_seq"]) for e in out if e["namespace"] != 2}
    return [e for e in out if e["namespace"] != 2 or (e["ref_index"], e["ref_seq"]) not in longs]


def _inter_run_gaps(runs, cluster_size: int, total: int) -> list[tuple[int, int]]:
    gaps: list[tuple[int, int]] = []
    cursor = 0
    prev_end: int | None = None
    for _vcn, lcn, count in runs:
        if lcn == SPARSE:
            cursor += count * cluster_size
            continue
        start = lcn * cluster_size
        if prev_end is not None and start != prev_end:
            gaps.append((cursor, max(0, start - prev_end)))
        cursor += count * cluster_size
        prev_end = start + count * cluster_size
    return [g for g in gaps if g[1] > 0 and g[0] < total]


def _extension(name: str) -> str:
    if "." in name[1:]:
        return name.rsplit(".", 1)[1].lower()[:16]
    return ""
