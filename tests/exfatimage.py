"""Builds small exFAT volumes in memory, with deleted files placed on purpose.

The layout follows the spec closely enough for the exFAT reader and for
Windows' own idea of the boot sector: boot sector, FAT at sector 128, cluster
heap at sector 1024, allocation bitmap in cluster 2, an (empty) up-case table
in cluster 3, root directory in cluster 4. Deleting works the way Windows and
Linux do it: the in-use bit of every entry in the set is cleared and the
file's clusters are cleared in the bitmap; the FAT is left alone unless
``wipe_chain`` asks for the worst case.
"""

from __future__ import annotations

import struct

SECTOR = 512
CLUSTER = 4096
TOTAL = 16 << 20
FAT_SECTOR = 128
HEAP_SECTOR = 1024


def checksum(entries: bytes) -> int:
    chk = 0
    for i, b in enumerate(entries):
        if i in (2, 3):
            continue
        chk = ((((chk & 1) << 15) | (chk >> 1)) + b) & 0xFFFF
    return chk


def stamp(year: int = 2026, month: int = 8, day: int = 14, hour: int = 12, minute: int = 30) -> int:
    return ((year - 1980) << 25) | (month << 21) | (day << 16) | (hour << 11) | (minute << 5)


class ExfatBuilder:
    def __init__(self) -> None:
        self.image = bytearray(TOTAL)
        self.cluster_count = (TOTAL // SECTOR - HEAP_SECTOR) // (CLUSTER // SECTOR)
        self.fat = [0] * (self.cluster_count + 2)
        self.fat[0], self.fat[1] = 0xFFFFFFF8, 0xFFFFFFFF
        self.used = set()
        self.dirs: dict[int, bytearray] = {}
        self.next = 2
        self.bitmap_cluster = self._take(1)[0]
        self.upcase_cluster = self._take(1)[0]
        self.root = self._take(1)[0]
        self.dirs[self.root] = bytearray()
        bitmap_entry = bytearray(32)
        bitmap_entry[0] = 0x81
        struct.pack_into("<IQ", bitmap_entry, 20, self.bitmap_cluster, (self.cluster_count + 7) // 8)
        upcase_entry = bytearray(32)
        upcase_entry[0] = 0x82
        struct.pack_into("<IQ", upcase_entry, 20, self.upcase_cluster, 0)
        self.dirs[self.root] += bitmap_entry + upcase_entry

    def offset(self, cluster: int) -> int:
        return HEAP_SECTOR * SECTOR + (cluster - 2) * CLUSTER

    def _take(self, count: int, gap: int = 0) -> list[int]:
        """Allocate ``count`` clusters, ``gap`` free clusters between each (fragmentation)."""
        out = []
        for _ in range(count):
            out.append(self.next)
            self.used.add(self.next)
            self.next += 1 + gap
        for a, b in zip(out, out[1:]):
            self.fat[a] = b
        self.fat[out[-1]] = 0xFFFFFFFF
        return out

    def _write(self, clusters: list[int], data: bytes) -> None:
        for i, c in enumerate(clusters):
            piece = data[i * CLUSTER:(i + 1) * CLUSTER]
            self.image[self.offset(c):self.offset(c) + len(piece)] = piece

    def _entry_set(self, name: str, first: int, size: int, is_dir: bool, contiguous: bool,
                   deleted: bool) -> bytes:
        units = name.encode("utf-16-le")
        chunks = [units[i:i + 30] for i in range(0, len(units), 30)]
        file_e = bytearray(32)
        file_e[0] = 0x85
        file_e[1] = 1 + len(chunks)
        struct.pack_into("<H", file_e, 4, 0x10 if is_dir else 0x20)
        struct.pack_into("<III", file_e, 8, stamp(), stamp(), stamp())
        stream = bytearray(32)
        stream[0] = 0xC0
        stream[1] = 0x01 | (0x02 if contiguous else 0)
        stream[3] = len(name)
        struct.pack_into("<Q", stream, 8, size)
        struct.pack_into("<IQ", stream, 20, first, size)
        names = []
        for chunk in chunks:
            e = bytearray(32)
            e[0] = 0xC1
            e[2:2 + len(chunk)] = chunk
            names.append(e)
        entries = bytearray(file_e + stream + b"".join(names))
        struct.pack_into("<H", entries, 2, checksum(bytes(entries)))
        if deleted:
            for k in range(0, len(entries), 32):
                entries[k] &= 0x7F
        return bytes(entries)

    def add_dir(self, name: str, into: int | None = None, deleted: bool = False) -> int:
        cluster = self._take(1)[0]
        self.dirs[cluster] = bytearray()
        self.dirs[into or self.root] += self._entry_set(name, cluster, CLUSTER, True, True, deleted)
        if deleted:
            self.used.discard(cluster)
        return cluster

    def add_file(self, name: str, data: bytes, into: int | None = None, deleted: bool = False,
                 fragmented: bool = False, wipe_chain: bool = False) -> list[int]:
        count = max(1, -(-len(data) // CLUSTER))
        clusters = self._take(count, gap=1 if fragmented else 0)
        if fragmented:
            # The gaps belong to another (live) file: that is why it fragmented.
            self.used.update(range(clusters[0], clusters[-1] + 1))
        self._write(clusters, data)
        self.dirs[into or self.root] += self._entry_set(name, clusters[0], len(data), False,
                                                        not fragmented, deleted)
        if deleted:
            self.used.difference_update(clusters)
            if wipe_chain:
                for c in clusters:
                    self.fat[c] = 0
        return clusters

    def overwrite(self, clusters: list[int], data: bytes) -> None:
        """A later live file that took a deleted file's clusters."""
        self._write(clusters, data)
        self.used.update(clusters)

    def build(self) -> bytes:
        img = self.image
        boot = bytearray(SECTOR)
        boot[0:3] = b"\xeb\x76\x90"
        boot[3:11] = b"EXFAT   "
        fat_sectors = -(-len(self.fat) * 4 // SECTOR)
        struct.pack_into("<QQ", boot, 64, 0, TOTAL // SECTOR)
        struct.pack_into("<IIIII", boot, 80, FAT_SECTOR, fat_sectors, HEAP_SECTOR,
                         self.cluster_count, self.root)
        struct.pack_into("<IHH", boot, 100, 0x1234ABCD, 0x0100, 0)
        boot[108], boot[109], boot[110] = 9, 3, 1
        boot[510:512] = b"\x55\xaa"
        img[0:SECTOR] = boot
        fat = b"".join(struct.pack("<I", v) for v in self.fat)
        img[FAT_SECTOR * SECTOR:FAT_SECTOR * SECTOR + len(fat)] = fat
        bits = bytearray((self.cluster_count + 7) // 8)
        for c in self.used:
            bits[(c - 2) // 8] |= 1 << ((c - 2) % 8)
        img[self.offset(self.bitmap_cluster):self.offset(self.bitmap_cluster) + len(bits)] = bits
        for cluster, entries in self.dirs.items():
            img[self.offset(cluster):self.offset(cluster) + len(entries)] = entries
        return bytes(img)
