"""Synthetic filesystem images, written byte by byte.

These are not mountable images, but every structure the recovery code reads
is laid out exactly as the real filesystem writes it: boot sectors, master
tables, data runs, directory entries. That is what makes them useful for
testing recovery, which never mounts anything.
"""

from __future__ import annotations

import struct

from tizorecover.engine.fs import ntfs as N

MFT_LCN = 100
SECTOR = 512
CLUSTER = 4096
RECORD = 1024


ATTR_START = 0x38


def _usn_fix(record: bytearray, sector_size: int = SECTOR, usa_ofs: int = 0x2A) -> None:
    """Apply an update sequence array the way NTFS writes one."""
    usa_count = len(record) // sector_size + 1
    usn = b"\x37\x13"
    record[usa_ofs:usa_ofs + 2] = usn
    for i in range(1, usa_count):
        end = i * sector_size - 2
        record[usa_ofs + i * 2: usa_ofs + i * 2 + 2] = bytes(record[end:end + 2])
        record[end:end + 2] = usn
    struct.pack_into("<HH", record, 4, usa_ofs, usa_count)


def attr_resident(atype: int, value: bytes, name: str = "", indexed: bool = False) -> bytes:
    name_b = name.encode("utf-16-le")
    head = 0x18
    total = head + len(name_b) + len(value)
    total = (total + 7) & ~7
    out = bytearray(total)
    struct.pack_into("<IIBBHHH", out, 0, atype, total, 0, len(name), head if name_b else 0, 0, 0)  # length in characters
    struct.pack_into("<IHB", out, 0x10, len(value), head + len(name_b), 1 if indexed else 0)
    out[head:head + len(name_b)] = name_b
    out[head + len(name_b):head + len(name_b) + len(value)] = value
    return bytes(out)


def encode_runs(runs: list[tuple[int, int]]) -> bytes:
    """Encode (lcn, clusters) pairs as an NTFS runlist.

    Each run's LCN is stored as a signed delta from the *previous run's* LCN,
    not from where the previous run ended, so a fragmented file like the $MFT
    encodes correctly.
    """
    out = bytearray()
    previous = 0
    for lcn, count in runs:
        delta = lcn - previous
        lb = _unsigned_bytes(count)
        db = _signed_bytes(delta)
        out.append((len(db) << 4) | len(lb))
        out += lb + db
        previous = lcn
    return bytes(out)


def _unsigned_bytes(value: int) -> bytes:
    n = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(n, "little")


def _signed_bytes(value: int) -> bytes:
    n = 1
    while not -(1 << (8 * n - 1)) <= value < (1 << (8 * n - 1)):
        n += 1
    return value.to_bytes(n, "little", signed=True)


def attr_nonresident(atype: int, runs: list[tuple[int, int]], real_size: int,
                     allocated: int, start_vcn: int = 0, name: str = "") -> bytes:
    name_b = name.encode("utf-16-le")
    runlist = encode_runs(runs)
    head = 0x40
    total = head + len(name_b) + len(runlist)
    total = (total + 7) & ~7
    out = bytearray(total)
    struct.pack_into("<IIBBHHH", out, 0, atype, total, 1, len(name), head if name_b else 0, 0, 0)  # length in characters
    last_vcn = start_vcn + sum(c for _l, c in runs) - 1
    struct.pack_into("<Q", out, 0x10, start_vcn)
    struct.pack_into("<q", out, 0x18, last_vcn)
    struct.pack_into("<H", out, 0x20, head + len(name_b))
    struct.pack_into("<Q", out, 0x28, allocated)
    struct.pack_into("<Q", out, 0x30, real_size)
    struct.pack_into("<Q", out, 0x38, real_size)
    out[head:head + len(name_b)] = name_b
    out[head + len(name_b):head + len(name_b) + len(runlist)] = runlist
    return bytes(out)


def file_name_attr(name: str, parent_index: int, real_size: int,
                   namespace: int = 3, parent_seq: int = 5) -> bytes:
    name_b = name.encode("utf-16-le")
    v = bytearray(0x42 + len(name_b))
    struct.pack_into("<Q", v, 0, (parent_seq << 48) | parent_index)
    for off in (0x08, 0x10, 0x18, 0x20):
        struct.pack_into("<Q", v, off, 0x01DA000000000000)
    struct.pack_into("<Q", v, 0x28, ((real_size + CLUSTER - 1) // CLUSTER) * CLUSTER)
    struct.pack_into("<Q", v, 0x30, real_size)
    struct.pack_into("<I", v, 0x38, 0x20)
    v[0x40] = len(name)
    v[0x41] = namespace
    v[0x42:] = name_b
    return bytes(v)


def std_info(created: int = 0x01DA000000000000) -> bytes:
    return struct.pack("<QQQQIIII", created, created, created, created, 0, 0, 0, 0)


def attribute_list(entries: list[tuple[int, int, int, int, str]]) -> bytes:
    """Build a resident $ATTRIBUTE_LIST pointing at attributes in other records.

    ``entries`` are ``(attribute_type, target_record, offset_in_target, start_vcn, name)``.
    """
    out = bytearray()
    for atype, target, offset, start_vcn, name in entries:
        name_b = name.encode("utf-16-le")
        entry = bytearray(26)
        struct.pack_into("<I", entry, 0, atype)
        struct.pack_into("<H", entry, 4, 26)
        struct.pack_into("<B", entry, 6, len(name_b))
        struct.pack_into("<B", entry, 7, 26)
        struct.pack_into("<Q", entry, 8, start_vcn)
        struct.pack_into("<Q", entry, 16, target & 0x0000FFFFFFFFFFFF)
        struct.pack_into("<H", entry, 24, 0)
        out += entry + name_b
    return bytes(out)


def mft_record(index: int, attrs: list[bytes], in_use: bool, is_dir: bool = False,
               sequence: int = 1) -> bytes:
    rec = bytearray(RECORD)
    rec[0:4] = b"FILE"
    body = b"".join(attrs) + b"\xff\xff\xff\xff"
    struct.pack_into("<Q", rec, 0x08, 0)
    struct.pack_into("<H", rec, 0x10, sequence)
    struct.pack_into("<H", rec, 0x12, 1)
    struct.pack_into("<H", rec, 0x14, ATTR_START)
    struct.pack_into("<H", rec, 0x16, (1 if in_use else 0) | (2 if is_dir else 0))
    struct.pack_into("<I", rec, 0x18, ATTR_START + len(body))
    struct.pack_into("<I", rec, 0x1C, RECORD)
    struct.pack_into("<Q", rec, 0x20, 0)
    struct.pack_into("<H", rec, 0x28, len(attrs) + 1)
    rec[ATTR_START:ATTR_START + len(body)] = body
    _usn_fix(rec)
    return bytes(rec)


class NtfsBuilder:
    """Assemble a volume holding a few live and deleted files."""

    def __init__(self, total_clusters: int = 16384,
                 mft_fragments: int = 0,
                 mft_fragment_lcns: tuple[int, ...] = ()) -> None:
        self.mft_fragments = int(mft_fragments)
        self.mft_fragment_lcns = tuple(mft_fragment_lcns)
        self.size = total_clusters * CLUSTER
        self.image = bytearray(self.size)
        self.records: dict[int, bytes] = {}
        self.next_index = 16
        self.next_lcn = 200

    def add_dir(self, name: str, parent_index: int = 5) -> int:
        index = self.next_index
        self.next_index += 1
        attrs = [
            attr_resident(N.ATTR_STANDARD_INFORMATION, std_info()),
            attr_resident(N.ATTR_FILE_NAME, file_name_attr(name, parent_index, 0, namespace=1)),
        ]
        attrs.append(attr_nonresident(N.ATTR_DATA, b"", 0, 0))
        self.records[index] = mft_record(index, attrs, in_use=True, is_dir=True)
        return index

    def add_live_file(self, name: str, data: bytes, parent_index: int = 5) -> int:
        return self._add(name, data, parent_index, in_use=True)

    def add_deleted_file(self, name: str, data: bytes, parent_index: int = 5,
                         extents: int = 1, resident: bool = False) -> int:
        return self._add(name, data, parent_index, in_use=False, extents=extents,
                         resident=resident)

    def _add(self, name: str, data: bytes, parent_index: int, in_use: bool,
             extents: int = 1, resident: bool = False) -> int:
        index = self.next_index
        self.next_index += 1
        attrs = [attr_resident(N.ATTR_STANDARD_INFORMATION, std_info())]
        attrs.append(attr_resident(N.ATTR_FILE_NAME, file_name_attr(name, parent_index, len(data))))
        if resident:
            attrs.append(attr_resident(N.ATTR_DATA, data))
        else:
            runs = []
            remaining = data
            first_lcn = self.next_lcn
            per = max(1, (len(data) + extents - 1) // extents)
            pos = 0
            for i in range(extents):
                piece = remaining[pos:pos + per]
                if not piece and i:
                    continue
                if not piece:
                    piece = b"\x00"
                lcn = self.next_lcn
                count = max(1, (len(piece) + CLUSTER - 1) // CLUSTER)
                self._write_clusters(lcn, piece)
                runs.append((lcn, count))
                pos += len(piece)
                self.next_lcn += count + 3
            total = sum(c for _l, c in runs) * CLUSTER
            attrs.append(attr_nonresident(N.ATTR_DATA, runs, len(data), total))
        self.records[index] = mft_record(index, attrs, in_use=in_use)
        return index

    def _write_clusters(self, lcn: int, data: bytes) -> None:
        start = lcn * CLUSTER
        self.image[start:start + len(data)] = data

    def build(self) -> bytes:
        self._write_boot()
        if self.mft_fragments:
            self._write_fragmented_mft()
        else:
            for index, rec in self.records.items():
                start = MFT_LCN * CLUSTER + index * RECORD
                self.image[start:start + len(rec)] = rec
            self._write_mft_record_zero()
        return bytes(self.image)

    def _write_fragmented_mft(self) -> None:
        """Scatter the MFT over several extents, the way a real volume does.

        A real $MFT is a fragmented file: its first extent holds only a part of
        the records and the rest sit in extents scattered across the disk.
        Building it contiguously hid a bug where the walker computed every
        record's address as ``$MFT start + index * record_size``.

        The index space 0..highest is split into contiguous ranges, one per
        extent, so record *n* really does sit in the extent that covers *n* --
        which is what the runlist says and what the walker relies on.
        """
        pieces = self.mft_fragments
        highest = max(self.records)
        span = highest + 1
        per_cluster = max(1, CLUSTER // RECORD)
        chunks = max(1, -(-span // (pieces * per_cluster)))
        per_extent = chunks * per_cluster
        runs: list[tuple[int, int, int]] = []
        cursor = 0
        for slot in range(pieces):
            low = slot * per_extent
            high = min(span, low + per_extent)
            if low >= high:
                break
            lcn = MFT_LCN if slot == 0 else self.mft_fragment_lcns[slot - 1]
            clusters = max(1, -(-((high - low) * RECORD) // CLUSTER))
            runs.append((cursor, lcn, clusters))
            base = lcn * CLUSTER
            for index in range(low, high):
                rec = self.records.get(index)
                if rec is None:
                    continue
                start = base + (index - low) * RECORD
                self.image[start:start + len(rec)] = rec
            cursor += clusters

        attrs = [
            attr_resident(N.ATTR_STANDARD_INFORMATION, std_info()),
            attr_resident(N.ATTR_FILE_NAME, file_name_attr("$MFT", 5, 0, namespace=1)),
            attr_nonresident(N.ATTR_DATA, [(lcn, count) for _v, lcn, count in runs],
                             span * RECORD, cursor * CLUSTER),
        ]
        rec = mft_record(0, attrs, in_use=True)
        start = runs[0][1] * CLUSTER
        self.image[start:start + len(rec)] = rec

    def _write_boot(self) -> None:
        b = bytearray(512)
        b[0:3] = b"\xeb\x52\x90"
        b[3:11] = b"NTFS    "
        struct.pack_into("<H", b, 0x0B, SECTOR)
        b[0x0D] = CLUSTER // SECTOR
        struct.pack_into("<H", b, 0x0E, 0)
        struct.pack_into("<B", b, 0x15, 0xF8)
        struct.pack_into("<Q", b, 0x28, self.size // SECTOR)
        struct.pack_into("<Q", b, 0x30, MFT_LCN)
        struct.pack_into("<Q", b, 0x38, 2)
        b[0x40] = 0xF6
        b[0x41] = 0x00
        struct.pack_into("<h", b, 0x42, 0xF6)
        struct.pack_into("<I", b, 0x44, 0xDEADBEEF)
        struct.pack_into("<I", b, 0x48, 0)
        b[510:512] = b"\x55\xaa"
        self.image[0:512] = b

    def _write_mft_record_zero(self) -> None:
        attrs = [
            attr_resident(N.ATTR_STANDARD_INFORMATION, std_info()),
            attr_resident(N.ATTR_FILE_NAME, file_name_attr("$MFT", 5, 0, namespace=1)),
            attr_nonresident(N.ATTR_DATA, [(MFT_LCN, 64)], 0, 64 * CLUSTER),
        ]
        rec = mft_record(0, attrs, in_use=True)
        start = MFT_LCN * CLUSTER
        self.image[start:start + len(rec)] = rec


FAT_SECTOR = 512
FAT_CLUSTER = 4096
FAT_RESERVED = 32
FAT_COUNT = 2
FAT_TOTAL_SECTORS = 32768
FAT_SIZE_SECTORS = 128


FAT_BASE = FAT_RESERVED * FAT_SECTOR


def _fat_entry(image: bytearray, cluster: int, value: int) -> None:
    struct.pack_into("<I", image, FAT_BASE + cluster * 4, value & 0x0FFFFFFF)


def _lfn_slots(name: str) -> list[bytes]:
    encoded = name.encode("utf-16-le") + b"\x00\x00"
    slots = []
    per = 13
    chunks = [encoded[i:i + per * 2] for i in range(0, len(encoded), per * 2)]
    for i, chunk in enumerate(chunks):
        padded = chunk + b"\xff" * (per * 2 - len(chunk))
        slot = bytearray(32)
        slot[0] = i + 1
        slot[0x01:0x0B] = padded[0:10]
        slot[0x0B] = 0x0F
        slot[0x0C] = 0
        slot[0x0D] = 0
        slot[0x0E:0x1A] = padded[10:22]
        slot[0x1A:0x1C] = b"\x00\x00"
        slot[0x1C:0x20] = padded[22:26]
        assert len(slot) == 32, f"LFN slot is {len(slot)} bytes, not 32"
        slots.append(bytes(slot))
    return list(reversed(slots))


def _short_entry(name: str, cluster: int, size: int, attr: int, deleted: bool) -> bytes:
    base = "".join(c for c in name.upper() if c.isalnum() or c in "-_")[:8] or "FILE"
    ext = name.rsplit(".", 1)[1].upper()[:3] if "." in name else ""
    slot = bytearray(32)
    if deleted:
        slot[0] = 0xE5
    else:
        slot[0] = base[0].encode()[0]
    slot[1:11] = (base[1:] + ext).encode()[:10].ljust(10, b" ")
    slot[0x0B] = attr
    struct.pack_into("<H", slot, 0x14, cluster >> 16)
    struct.pack_into("<H", slot, 0x16, 0x6000)
    struct.pack_into("<H", slot, 0x18, 0x573F)
    struct.pack_into("<H", slot, 0x1A, cluster & 0xFFFF)
    struct.pack_into("<I", slot, 0x1C, size)
    assert len(slot) == 32, f"short entry is {len(slot)} bytes, not 32"
    return bytes(slot)


class Fat32Builder:
    def __init__(self):
        self.size = FAT_TOTAL_SECTORS * FAT_SECTOR
        self.data_start = FAT_RESERVED + FAT_COUNT * FAT_SIZE_SECTORS
        self.cluster_count = (FAT_TOTAL_SECTORS - self.data_start) // (FAT_CLUSTER // FAT_SECTOR)
        self.next_cluster = 3
        self.root = bytearray()
        self.dirs: dict[int, bytearray] = {}
        self.image = bytearray(self.size)

    def _cluster_offset(self, cluster: int) -> int:
        return self.data_start * FAT_SECTOR + (cluster - 2) * FAT_CLUSTER

    def _allocate(self, payload: bytes) -> tuple[int, int]:
        """Write payload into a fresh cluster chain, return (start, count)."""
        start = self.next_cluster
        count = max(1, (len(payload) + FAT_CLUSTER - 1) // FAT_CLUSTER)
        padded = payload + b"\x00" * (count * FAT_CLUSTER - len(payload))
        for i in range(count):
            off = self._cluster_offset(start + i)
            self.image[off:off + FAT_CLUSTER] = padded[i * FAT_CLUSTER:(i + 1) * FAT_CLUSTER]
        for i in range(count - 1):
            _fat_entry(self.image, start + i, start + i + 1)
        _fat_entry(self.image, start + count - 1, 0x0FFFFFFF)
        self.next_cluster += count
        return start, count

    def _buffer(self, into: int | None) -> bytearray:
        if into is None:
            return self.root
        return self.dirs.setdefault(into, bytearray())

    def add_dir(self, name: str, deleted: bool = False, into: int | None = None) -> int:
        cluster, _ = self._allocate(b"")
        self.dirs.setdefault(cluster, bytearray())
        buf = self._buffer(into)
        for slot in _lfn_slots(name):
            buf += slot
        buf += _short_entry(name, cluster, 0, 0x10, deleted=deleted)
        return cluster

    def add_live_file(self, name: str, payload: bytes, into: int | None = None) -> None:
        start, _ = self._allocate(payload)
        buf = self._buffer(into)
        for slot in _lfn_slots(name):
            buf += slot
        buf += _short_entry(name, start, len(payload), 0x20, deleted=False)

    def add_deleted_file(self, name: str, payload: bytes, into: int | None = None,
                         free_chain: bool = False) -> int:
        """Add a deleted file. ``free_chain`` zeroes its FAT entries, as Windows does."""
        start, count = self._allocate(payload)
        if free_chain:
            for i in range(count):
                _fat_entry(self.image, start + i, 0)
        buf = self._buffer(into)
        for slot in _lfn_slots(name):
            buf += slot
        buf += _short_entry(name, start, len(payload), 0x20, deleted=True)
        return start

    def build(self) -> bytes:
        _fat_entry(self.image, 0, 0x0FFFFFF8)
        _fat_entry(self.image, 1, 0x0FFFFFFF)
        boot = bytearray(FAT_SECTOR)
        boot[0:3] = b"\xeb\x58\x90"
        boot[3:11] = b"mkfs.fat"
        struct.pack_into("<H", boot, 0x0B, FAT_SECTOR)
        boot[0x0D] = FAT_CLUSTER // FAT_SECTOR
        struct.pack_into("<H", boot, 0x0E, FAT_RESERVED)
        boot[0x10] = FAT_COUNT
        struct.pack_into("<H", boot, 0x11, 0)
        struct.pack_into("<H", boot, 0x13, 0)
        boot[0x15] = 0xF8
        struct.pack_into("<I", boot, 0x20, FAT_TOTAL_SECTORS)
        struct.pack_into("<I", boot, 0x24, FAT_SIZE_SECTORS)
        struct.pack_into("<I", boot, 0x2C, 2)
        struct.pack_into("<H", boot, 0x30, 1)
        struct.pack_into("<H", boot, 0x32, 6)
        boot[0x52:0x5A] = b"FAT32   "
        boot[510:512] = b"\x55\xaa"
        self.image[0:FAT_SECTOR] = boot
        self._write_dir(2, self.root)
        for cluster, entries in self.dirs.items():
            self._write_dir(cluster, entries)
        return bytes(self.image)

    def _write_dir(self, cluster: int, entries: bytes) -> None:
        if not entries:
            return
        pad = (-len(entries)) % FAT_CLUSTER
        padded = entries + b"\x00" * pad
        for i in range(len(padded) // FAT_CLUSTER):
            off = self._cluster_offset(cluster + i)
            self.image[off:off + FAT_CLUSTER] = padded[i * FAT_CLUSTER:(i + 1) * FAT_CLUSTER]
