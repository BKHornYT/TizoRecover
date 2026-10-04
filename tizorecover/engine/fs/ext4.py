"""ext2/3/4: files with names and folders, from the tree and from the journal.

Two cases, two techniques:

* **A lost or formatted-over Linux partition** (a phone, a Raspberry Pi card,
  an old install on a USB stick): its files were never deleted, so the
  directory tree and the inodes still describe all of them. Walking the tree
  from the root brings back every file by name, as long as the metadata has
  not been overwritten by whatever uses the space now.

* **Deleted files on an ext4 volume:** deleting wipes the inode's size and
  block map and, on current kernels, the name in the directory too. What
  survives is the *journal*: it holds older copies of inode-table and
  directory blocks, written while the file still existed. Every journal copy
  of a directory block is read for names whose inode is now deleted, and the
  newest journal copy of that inode supplies size, dates and block map.
  This is what extundelete and ext4magic do.

Block maps are turned into volume extents, with holes (sparse ranges and
unwritten extents) read as zeros.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Iterator

from tizorecover.engine.results import FileCandidate, Strategy, Verdict

EXT_MAGIC = 0xEF53
EXTENTS_FL = 0x80000
INLINE_FL = 0x10000000
EXTENT_MAGIC = 0xF30A
JBD2_MAGIC = 0xC03B3998
ROOT_INO = 2
JOURNAL_INO = 8
S_IFDIR, S_IFREG, S_IFLNK = 0x4000, 0x8000, 0xA000
MAX_DIR_BYTES = 64 << 20
MAX_EXTENTS = 100000


@dataclass
class ExtInfo:
    block: int
    blocks: int
    first_data_block: int
    blocks_per_group: int
    inodes_per_group: int
    inode_size: int
    inodes: int
    desc_size: int
    incompat: int
    journal_ino: int
    label: str
    groups: list[tuple[int, int, int]] = field(default_factory=list)   # (block bitmap, inode bitmap, inode table)

    @property
    def is64(self) -> bool:
        return bool(self.incompat & 0x80)


def read_super(src) -> ExtInfo | None:
    sb = src.at(1024, 1024)
    if len(sb) < 1024 or struct.unpack_from("<H", sb, 0x38)[0] != EXT_MAGIC:
        return None
    log = struct.unpack_from("<I", sb, 0x18)[0]
    if log > 6:
        return None
    block = 1024 << log
    incompat = struct.unpack_from("<I", sb, 0x60)[0]
    blocks = struct.unpack_from("<I", sb, 0x04)[0]
    if incompat & 0x80:
        blocks |= struct.unpack_from("<I", sb, 0x150)[0] << 32
    rev = struct.unpack_from("<I", sb, 0x4C)[0]
    inode_size = struct.unpack_from("<H", sb, 0x58)[0] if rev >= 1 else 128
    desc_size = struct.unpack_from("<H", sb, 0xFE)[0] if incompat & 0x80 else 32
    info = ExtInfo(
        block=block, blocks=blocks, first_data_block=struct.unpack_from("<I", sb, 0x14)[0],
        blocks_per_group=struct.unpack_from("<I", sb, 0x20)[0],
        inodes_per_group=struct.unpack_from("<I", sb, 0x28)[0], inode_size=inode_size or 128,
        inodes=struct.unpack_from("<I", sb, 0x00)[0], desc_size=max(32, desc_size or 32), incompat=incompat,
        journal_ino=struct.unpack_from("<I", sb, 0xE0)[0] or JOURNAL_INO,
        label=sb[0x78:0x88].split(b"\x00")[0].decode("utf-8", "replace"),
    )
    if not info.blocks_per_group or not info.inodes_per_group or info.inode_size < 128:
        return None
    count = -(-(info.blocks - info.first_data_block) // info.blocks_per_group)
    table = src.at((info.first_data_block + 1) * block, count * info.desc_size)
    for g in range(count):
        d = table[g * info.desc_size:(g + 1) * info.desc_size]
        if len(d) < 32:
            break
        bb, ib, it = struct.unpack_from("<III", d, 0)
        if info.is64 and len(d) >= 64:
            bbh, ibh, ith = struct.unpack_from("<III", d, 0x20)
            bb, ib, it = bb | bbh << 32, ib | ibh << 32, it | ith << 32
        info.groups.append((bb, ib, it))
    return info


# ---------------------------------------------------------------- inodes

@dataclass
class Inode:
    number: int
    mode: int
    size: int
    links: int
    flags: int
    dtime: int
    mtime: int
    block: bytes          # i_block, 60 bytes

    @property
    def kind(self) -> int:
        return self.mode & 0xF000


def inode_location(info: ExtInfo, ino: int) -> tuple[int, int] | None:
    """(file-system block holding inode ``ino``, byte offset inside it)."""
    if ino < 1:
        return None
    group, index = divmod(ino - 1, info.inodes_per_group)
    if group >= len(info.groups):
        return None
    byte = info.groups[group][2] * info.block + index * info.inode_size
    return byte // info.block, byte % info.block


def parse_inode(raw: bytes, ino: int) -> Inode | None:
    if len(raw) < 128:
        return None
    mode, = struct.unpack_from("<H", raw, 0)
    size = struct.unpack_from("<I", raw, 4)[0] | struct.unpack_from("<I", raw, 0x6C)[0] << 32
    return Inode(ino, mode, size, struct.unpack_from("<H", raw, 0x1A)[0], struct.unpack_from("<I", raw, 0x20)[0],
                 struct.unpack_from("<I", raw, 0x14)[0], struct.unpack_from("<I", raw, 0x10)[0], raw[0x28:0x64])


def read_inode(src, info: ExtInfo, ino: int) -> Inode | None:
    where = inode_location(info, ino)
    if where is None:
        return None
    blk, inner = where
    return parse_inode(src.at(blk * info.block + inner, info.inode_size), ino)


def block_runs(src, info: ExtInfo, inode: Inode) -> list[tuple[int, int, int]] | None:
    """``(logical block, physical block or -1, count)`` runs, or None if the map is unreadable."""
    if inode.flags & INLINE_FL:
        return []
    if inode.flags & EXTENTS_FL:
        out: list[tuple[int, int, int]] = []
        if not _extent_node(src, info, inode.block, out, 0):
            return None
        return out
    return _indirect_runs(src, info, inode)


def _extent_node(src, info: ExtInfo, node: bytes, out: list, depth_seen: int) -> bool:
    if len(node) < 12 or depth_seen > 6:
        return False
    magic, entries, _max, depth = struct.unpack_from("<HHHH", node, 0)
    if magic != EXTENT_MAGIC or entries > 340:
        return False
    for k in range(entries):
        e = node[12 + k * 12:24 + k * 12]
        if len(e) < 12:
            return False
        if depth == 0:
            lblk, length, hi, lo = struct.unpack("<IHHI", e)
            unwritten = length > 32768
            count = length - 32768 if unwritten else length
            phys = lo | hi << 32
            if phys + count > info.blocks or count == 0:
                return False
            out.append((lblk, -1 if unwritten else phys, count))
            if len(out) > MAX_EXTENTS:
                return False
        else:
            _lblk, lo, hi = struct.unpack("<IIH2x", e)
            child = lo | hi << 32
            if child >= info.blocks:
                return False
            if not _extent_node(src, info, src.at(child * info.block, info.block), out, depth_seen + 1):
                return False
    return True


def _indirect_runs(src, info: ExtInfo, inode: Inode) -> list[tuple[int, int, int]] | None:
    ptrs = list(struct.unpack("<15I", inode.block))
    per = info.block // 4
    need = -(-inode.size // info.block)
    blocks: list[int] = []

    def walk(blk: int, level: int) -> None:
        if len(blocks) >= need or blk == 0 or blk >= info.blocks:
            if blk == 0 and level == 0:
                blocks.append(0)
            return
        if level == 0:
            blocks.append(blk)
            return
        table = src.at(blk * info.block, info.block)
        for p in struct.unpack(f"<{per}I", table[:per * 4]):
            if len(blocks) >= need:
                return
            if p == 0:
                blocks.extend([0] * min(need - len(blocks), per ** (level - 1)))
                continue
            walk(p, level - 1)

    for p in ptrs[:12]:
        if len(blocks) >= need:
            break
        blocks.append(p)
    for level, p in ((1, ptrs[12]), (2, ptrs[13]), (3, ptrs[14])):
        if len(blocks) < need and p:
            walk(p, level)
    runs: list[tuple[int, int, int]] = []
    for i, b in enumerate(blocks[:need]):
        phys = b if b else -1
        if runs and runs[-1][0] + runs[-1][2] == i and (
                (phys == -1 and runs[-1][1] == -1) or (phys != -1 and runs[-1][1] != -1 and runs[-1][1] + runs[-1][2] == phys)):
            runs[-1] = (runs[-1][0], runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((i, phys, 1))
    return runs


def runs_to_extents(info: ExtInfo, runs: list[tuple[int, int, int]], size: int) -> list[tuple[int, int]]:
    """Volume ``(offset, length)`` pieces in file order; offset -1 for a hole."""
    out: list[tuple[int, int]] = []
    pos = 0
    for lblk, phys, count in sorted(runs):
        start = lblk * info.block
        if start >= size:
            break
        if start > pos:
            out.append((-1, start - pos))
            pos = start
        length = min(count * info.block, size - pos)
        out.append((-1 if phys < 0 else phys * info.block, length))
        pos += length
    if pos < size:
        out.append((-1, size - pos))
    return out


def read_file(src, info: ExtInfo, inode: Inode, limit: int = MAX_DIR_BYTES) -> bytes:
    if inode.flags & INLINE_FL:
        return inode.block[:min(inode.size, 60)]
    runs = block_runs(src, info, inode)
    if runs is None:
        return b""
    out = bytearray()
    for off, length in runs_to_extents(info, runs, min(inode.size, limit)):
        out += bytes(length) if off < 0 else src.at(off, length)
    return bytes(out)


# ---------------------------------------------------------------- directories

def parse_dir_block(raw: bytes) -> Iterator[tuple[int, str, int]]:
    """(inode, name, file type) of the live entries in one directory block."""
    pos = 0
    n = len(raw)
    while pos + 8 <= n:
        ino, rec_len, name_len, ftype = struct.unpack_from("<IHBB", raw, pos)
        if rec_len < 8 or rec_len % 4 or pos + rec_len > n:
            return
        if ino and name_len and 8 + name_len <= rec_len:
            name = raw[pos + 8:pos + 8 + name_len].decode("utf-8", "replace")
            if name not in (".", ".."):
                yield ino, name, ftype
        pos += rec_len


def _looks_like_dir_block(raw: bytes) -> bool:
    """A block whose entries chain exactly to its end (how journal copies are recognised)."""
    pos = 0
    entries = 0
    while pos + 8 <= len(raw):
        rec_len = struct.unpack_from("<H", raw, pos + 4)[0]
        name_len = raw[pos + 6]
        if rec_len < 8 or rec_len % 4 or pos + rec_len > len(raw) or 8 + name_len > rec_len:
            return False
        pos += rec_len
        entries += 1
    return pos == len(raw) and entries > 0


def _sanitise(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip() or "_"


def _ext_of(name: str) -> str:
    return name.rsplit(".", 1)[1].lower()[:16] if "." in name[1:] else ""


# ---------------------------------------------------------------- journal

class Journal:
    """Every copy of a file-system block the journal still holds, newest first."""

    def __init__(self, src, info: ExtInfo) -> None:
        self.copies: dict[int, list[tuple[int, int]]] = {}    # fs block -> [(sequence, byte offset)]
        self.src = src
        self.info = info
        inode = read_inode(src, info, info.journal_ino)
        if inode is None or not inode.size:
            return
        runs = block_runs(src, info, inode)
        if not runs:
            return
        # Journal block number -> byte offset on the volume.
        self.where: list[int] = []
        for lblk, phys, count in sorted(runs):
            while len(self.where) < lblk:
                self.where.append(-1)
            for k in range(count):
                self.where.append(-1 if phys < 0 else (phys + k) * info.block)
        self._scan()

    def _scan(self) -> None:
        if not self.where or self.where[0] < 0:
            return
        jsb = self.src.at(self.where[0], 1024)
        if len(jsb) < 1024 or struct.unpack_from(">I", jsb, 0)[0] != JBD2_MAGIC:
            return
        incompat = struct.unpack_from(">I", jsb, 0x28)[0]
        csum3 = bool(incompat & 0x10)
        is64 = bool(incompat & 0x2)
        tag_size = 16 if csum3 else (12 if is64 else 8)
        n = len(self.where)
        for j in range(1, n):
            off = self.where[j]
            if off < 0:
                continue
            head = self.src.at(off, 12)
            if len(head) < 12 or struct.unpack_from(">I", head, 0)[0] != JBD2_MAGIC:
                continue
            btype, seq = struct.unpack_from(">II", head, 4)
            if btype != 1:                                   # descriptor block
                continue
            desc = self.src.at(off, self.info.block)
            pos = 12
            data = j + 1
            first = True
            while pos + tag_size <= len(desc) - (4 if csum3 or incompat & 0x8 else 0):
                if csum3:
                    lo, flags, hi = struct.unpack_from(">III", desc, pos)
                else:
                    lo, = struct.unpack_from(">I", desc, pos)
                    flags = struct.unpack_from(">H", desc, pos + 6)[0]
                    hi = struct.unpack_from(">I", desc, pos + 8)[0] if is64 else 0
                fs_block = lo | (hi << 32 if is64 else 0)
                pos += tag_size
                if not flags & 0x2:                          # SAME_UUID unset: a UUID follows
                    pos += 16 if first else 16
                first = False
                if data >= n:
                    data = 1                                 # the log wraps around
                if not flags & 0x1 and self.where[data] >= 0 and fs_block < self.info.blocks:
                    self.copies.setdefault(fs_block, []).append((seq, self.where[data]))
                data += 1
                if flags & 0x8:                              # last tag
                    break
        for lst in self.copies.values():
            lst.sort(reverse=True)

    def blocks(self, fs_block: int) -> Iterator[bytes]:
        for _seq, off in self.copies.get(fs_block, []):
            yield self.src.at(off, self.info.block)

    def old_inode(self, ino: int) -> Inode | None:
        """The newest journal copy of ``ino`` taken while the file still existed."""
        where = inode_location(self.info, ino)
        if where is None:
            return None
        blk, inner = where
        for raw in self.blocks(blk):
            inode = parse_inode(raw[inner:inner + self.info.inode_size], ino)
            if inode is not None and inode.links and not inode.dtime and inode.size and (
                    inode.flags & (EXTENTS_FL | INLINE_FL) or any(inode.block)):
                return inode
        return None


# ---------------------------------------------------------------- recovery

def recover_ext(
    src,
    volume: str,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    include_live: bool = False,
    max_depth: int = 64,
) -> Iterator[FileCandidate]:
    """Every deleted file the journal still remembers; with ``include_live``, every live file too."""
    info = read_super(src)
    if info is None:
        return
    journal = Journal(src, info)
    dirs: dict[int, str] = {ROOT_INO: ""}          # live directory inode -> path
    dir_blocks: dict[int, int] = {}                # fs block -> directory inode
    seen_names: set[tuple[int, str]] = set()
    stack = [(ROOT_INO, "", 0)]
    visited: set[int] = set()
    while stack:
        if should_stop is not None and should_stop():
            return
        ino, path, depth = stack.pop()
        if ino in visited or depth > max_depth:
            continue
        visited.add(ino)
        inode = read_inode(src, info, ino)
        if inode is None or inode.kind != S_IFDIR:
            continue
        runs = block_runs(src, info, inode) or []
        for lblk, phys, count in runs:
            for k in range(count):
                if phys >= 0:
                    dir_blocks[phys + k] = ino
        raw = read_file(src, info, inode)
        if progress is not None:
            progress(len(raw))
        for b in range(0, len(raw), info.block):
            for child, name, _ftype in parse_dir_block(raw[b:b + info.block]):
                if child < 1 or child > info.inodes:
                    continue
                seen_names.add((ino, name))
                child_path = f"{path}/{_sanitise(name)}" if path else _sanitise(name)
                node = read_inode(src, info, child)
                if node is None:
                    continue
                if node.kind == S_IFDIR:
                    dirs[child] = child_path
                    stack.append((child, child_path, depth + 1))
                elif include_live and node.kind == S_IFREG and node.links:
                    cand = _candidate(src, info, node, name, child_path, volume, live=True)
                    if cand is not None:
                        yield cand

    # Deleted files: names from journal copies of directory blocks, data from
    # journal copies of their inodes. A deleted folder found this way is
    # opened the same way (its blocks, from the journal or the disk).
    queue: list[tuple[int, str, list[int], bool]] = []
    by_dir: dict[int, list[int]] = {}
    for blk, dir_ino in dir_blocks.items():
        by_dir.setdefault(dir_ino, []).append(blk)
    for dir_ino, blks in by_dir.items():
        queue.append((dir_ino, dirs.get(dir_ino, ""), blks, False))
    opened: set[int] = set(by_dir)
    while queue:
        if should_stop is not None and should_stop():
            return
        dir_ino, base, blks, folder_deleted = queue.pop(0)
        copies: list[bytes] = []
        for blk in blks:
            copies.extend(journal.blocks(blk))
            if folder_deleted:
                copies.append(src.at(blk * info.block, info.block))
        for raw in copies:
            if not _looks_like_dir_block(raw):
                continue
            for child, name, _ftype in parse_dir_block(raw):
                if (dir_ino, name) in seen_names or child < 1 or child > info.inodes:
                    continue
                now = read_inode(src, info, child)
                if now is None or (now.links and not now.dtime):
                    continue                          # still a live file (renamed, or reused inode)
                old = journal.old_inode(child)
                if old is None:
                    continue
                seen_names.add((dir_ino, name))
                path = f"{base}/{_sanitise(name)}" if base else _sanitise(name)
                if old.kind == S_IFDIR:
                    if child not in opened and len(opened) < 100000:
                        opened.add(child)
                        runs = block_runs(src, info, old) or []
                        sub = [phys + k for _l, phys, count in runs if phys >= 0 for k in range(count)]
                        queue.append((child, path, sub[:4096], True))
                    continue
                if old.kind not in (S_IFREG, 0):
                    continue
                cand = _candidate(src, info, old, name, path, volume, live=False)
                if cand is not None:
                    cand.metadata["folder_deleted"] = folder_deleted
                    yield cand


def _candidate(src, info: ExtInfo, inode: Inode, name: str, path: str, volume: str,
               live: bool) -> FileCandidate | None:
    if inode.size == 0:
        return None
    metadata: dict = {"inode": inode.number, "block_size": info.block, "modified": inode.mtime or None,
                      "live": bool(live)}
    if inode.flags & INLINE_FL:
        metadata["inline_data"] = inode.block[:min(inode.size, 60)]
        runs: list = []
    else:
        runs = block_runs(src, info, inode)
        if runs is None:
            return None
        metadata["extents"] = runs_to_extents(info, runs, inode.size)
    pieces = [r for r in runs if r[1] >= 0]
    reasons = ["in use when this volume was lost" if live else "deleted; size and block map from the journal"]
    reasons.append(f"inode {inode.number}, {len(pieces)} extent(s)")
    return FileCandidate(
        ext=_ext_of(name), size=inode.size, data_offset=-1, strategy=Strategy.EXT4,
        name=name, original_path=path, verdict=Verdict.VALID, confidence=0.85 if live else 0.75,
        reasons=reasons, volume=volume, fragment_count=max(1, len(pieces)), metadata=metadata,
    )


def bitmap(src, info: ExtInfo) -> bytes:
    """One byte per block (0 free, 1 used), from the block bitmaps."""
    out = bytearray()
    per = info.blocks_per_group
    for bb, _ib, _it in info.groups:
        raw = src.at(bb * info.block, per // 8)
        for byte in raw:
            out += bytes((byte >> bit) & 1 for bit in range(8))
    del out[max(0, info.blocks - info.first_data_block):]
    return bytes(out)
