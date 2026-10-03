"""One scan of one drive, run on a worker thread.

This is what the window and the command line both drive. A quick scan reads
the filesystem's own records (real names and folders, seconds to minutes); a
deep scan does that and then carves the volume's free space for files no
record mentions any more. Results stream into ``items`` as they are found, so
a front end can show them while the scan is still running, and the source
stays open afterwards so files can be previewed and saved.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from tizorecover.engine import allocation as alloc_mod
from tizorecover.engine import verify
from tizorecover.engine.access import CandidateData, pieces_of
from tizorecover.engine.blockdev import (BlockReader, DeviceBlockReader, VolumeAccessError,
                                         WindowBlockReader, open_source)
from tizorecover.engine.carver import carve_range
from tizorecover.engine.drives import Drive
from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.fs import fat as fat_fs
from tizorecover.engine.fs import ntfs as ntfs_fs
from tizorecover.engine.results import FileCandidate, Strategy
from tizorecover.engine.scan import detect_filesystem

QUICK = "quick"
DEEP = "deep"
MIN_FREE_RUN = 4096


class LockedSource:
    """A ``ByteSource`` whose reads are serialised.

    The scan thread and preview requests read the same handle at once; image
    files and Linux devices share one file position, so reads take turns.
    """

    def __init__(self, view: ByteSourceView) -> None:
        self._view = view
        self._lock = threading.Lock()
        self.size = view.size

    def at(self, offset: int, length: int) -> bytes:
        with self._lock:
            return self._view.at(offset, length)


@dataclass
class Item:
    """A found file as the front ends see it."""

    id: int
    candidate: FileCandidate
    status: str
    notes: list[str]
    category: str

    def to_dict(self) -> dict:
        c = self.candidate
        path = (c.original_path or "").replace("\\", "/")
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        return {
            "id": self.id,
            "name": c.name or os.path.basename(c.display_name),
            "folder": folder,
            "path": path,
            "ext": (c.ext or "").lower(),
            "size": c.size,
            "modified": c.metadata.get("modified"),
            "status": self.status,
            "category": self.category,
            "method": c.strategy.value,
            "named": bool(c.original_path),
            "fragments": max(1, len(pieces_of(c))),
            "folder_deleted": bool(c.metadata.get("folder_deleted")),
        }

    def details(self) -> dict:
        d = self.to_dict()
        d["reasons"] = list(self.candidate.reasons)
        d["notes"] = list(self.notes)
        d["confidence"] = round(self.candidate.confidence, 2)
        d["offset"] = (pieces_of(self.candidate) or [(-1, 0)])[0][0]
        return d


@dataclass
class Progress:
    stage: str = "starting"
    done: int = 0
    total: int = 0
    started: float = field(default_factory=time.time)
    stage_started: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        now = time.time()
        elapsed = now - self.started
        stage_elapsed = now - self.stage_started
        eta = None
        if self.total and self.done and stage_elapsed > 2:
            rate = self.done / stage_elapsed
            if rate > 0:
                eta = max(0.0, (self.total - self.done) / rate)
        return {"stage": self.stage, "done": self.done, "total": self.total,
                "elapsed": round(elapsed, 1), "eta": None if eta is None else round(eta)}


def open_drive(drive: Drive) -> BlockReader:
    """A reader over exactly the drive's bytes, whatever kind of drive it is."""
    if drive.kind == "partition":
        disk = DeviceBlockReader(drive.path)
        return WindowBlockReader(disk, drive.offset, drive.offset + drive.size,
                                 label=drive.id)
    return open_source(drive.path)


class ScanJob:
    """Runs one scan in the background and holds what it found."""

    def __init__(self, drive: Drive, mode: str = QUICK,
                 on_item: Callable[[Item], None] | None = None) -> None:
        self.drive = drive
        self.mode = mode
        self.on_item = on_item
        self.state = "starting"
        self.filesystem = "unknown"
        self.progress = Progress()
        self.items: list[Item] = []
        self.problems: list[str] = []
        self.free_bytes = 0
        self.reader: BlockReader | None = None
        self.src: LockedSource | None = None
        self.allocation = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fs_starts: dict[int, Item] = {}
        self.thread = threading.Thread(target=self._run, name="tizo-scan", daemon=True)

    def start(self) -> "ScanJob":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        self.thread.join(timeout)

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def item(self, item_id: int) -> Item | None:
        with self._lock:
            if 0 <= item_id < len(self.items):
                return self.items[item_id]
        return None

    def snapshot(self) -> list[Item]:
        with self._lock:
            return list(self.items)

    def data(self, item: Item) -> CandidateData:
        return CandidateData(item.candidate, self.src)

    def status(self) -> dict:
        with self._lock:
            counts = {verify.GOOD: 0, verify.PARTIAL: 0, verify.OVERWRITTEN: 0}
            for it in self.items:
                counts[it.status] = counts.get(it.status, 0) + 1
            total = len(self.items)
        return {"state": self.state, "mode": self.mode, "filesystem": self.filesystem,
                "drive": self.drive.to_dict(), "found": total, "counts": counts,
                "progress": self.progress.to_dict(), "problems": list(self.problems),
                "free_bytes": self.free_bytes}

    def close(self) -> None:
        self.stop()
        self.wait(5)
        if self.reader is not None:
            try:
                self.reader.close()
            except OSError:
                pass
            self.reader = None

    def _stage(self, name: str, total: int) -> None:
        self.progress.stage = name
        self.progress.done = 0
        self.progress.total = total
        self.progress.stage_started = time.time()

    def _advance(self, amount: int) -> None:
        self.progress.done += amount

    def _add(self, candidate: FileCandidate) -> None:
        if candidate.strategy is Strategy.CARVE:
            owner = self._fs_starts.get(candidate.data_offset)
            if owner is not None:
                note = f"confirmed by signature carving ({candidate.ext or '?'})"
                if note not in owner.candidate.reasons:
                    owner.candidate.reasons.append(note)
                return
        try:
            status, notes = verify.assess(candidate, self.src, self.allocation)
        except (OSError, ValueError) as exc:
            status, notes = verify.PARTIAL, [f"could not check: {exc}"]
        with self._lock:
            item = Item(len(self.items), candidate, status, notes,
                        verify.category_of(candidate.ext))
            self.items.append(item)
        pieces = pieces_of(candidate)
        if candidate.strategy is not Strategy.CARVE and pieces and pieces[0][0] >= 0:
            self._fs_starts.setdefault(pieces[0][0], item)
        if self.on_item is not None:
            self.on_item(item)

    def _run(self) -> None:
        self.state = "running"
        try:
            self._stage("opening", 0)
            self.reader = open_drive(self.drive)
            self.src = LockedSource(ByteSourceView(self.reader))
            self.filesystem = detect_filesystem(self.src)
            self.allocation = alloc_mod.detect(self.src, self.filesystem)
            if self.allocation is not None:
                self.free_bytes = self.allocation.free_bytes
            self._quick()
            if self.mode == DEEP and not self.stopping:
                self._deep()
            self.state = "stopped" if self.stopping else "done"
        except VolumeAccessError as exc:
            self.problems.append(str(exc))
            self.state = "failed"
        except Exception as exc:  # the UI must hear about it, whatever it is
            self.problems.append(f"scan failed: {exc!r}")
            self.state = "failed"
        self.progress.stage = self.state

    def _quick(self) -> None:
        fs = self.filesystem
        stop = self._stop.is_set
        if fs == "ntfs":
            boot = ntfs_fs.parse_boot_sector(self.src)
            mft = ntfs_fs.find_mft_start(self.src, boot) if boot else None
            mft_map = ntfs_fs.MftMap.locate(self.src, boot, mft) if mft is not None else None
            total = len(mft_map) * boot.mft_record_size if mft_map else 0
            self._stage("records", total)
            for cand in ntfs_fs.recover_ntfs(self.src, self.drive.id, progress=self._advance,
                                             should_stop=stop):
                self._add(cand)
            if not self.stopping:
                self.progress.done = self.progress.total
        elif fs in ("fat", "fat32"):
            self._stage("records", 0)
            for cand in fat_fs.recover_fat(self.src, self.drive.id, progress=self._advance,
                                           should_stop=stop):
                self._add(cand)
        elif fs == "exfat":
            self.problems.append("exFAT: deleted names are not read yet, so a quick scan "
                                 "finds nothing. Run a deep scan to find files by content.")
        else:
            self.problems.append(f"No readable filesystem ({fs}). Run a deep scan to find "
                                 f"files by their content.")

    def _deep(self) -> None:
        if self.allocation is not None:
            ranges = list(self.allocation.free_ranges(MIN_FREE_RUN))
        else:
            ranges = [(0, self.src.size)]
            if self.filesystem not in ("unknown",):
                self.problems.append("Could not read which space is free, so the deep scan "
                                     "reads the whole drive and may also list files that "
                                     "still exist.")
        self._stage("deep", sum(n for _o, n in ranges))
        stop = self._stop.is_set
        for offset, length in ranges:
            if stop():
                return
            for cand in carve_range(self.src, self.drive.id, start=offset, end=offset + length,
                                    progress=self._advance, should_stop=stop):
                self._add(cand)
