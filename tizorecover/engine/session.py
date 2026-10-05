"""One scan of one drive, run on a worker thread.

This is what the window and the command line both drive. A quick scan reads
the filesystem's own records (real names and folders, seconds to minutes); a
deep scan does that and then carves the volume's free space for files no
record mentions any more. Results stream into ``items`` as they are found, so
a front end can show them while the scan is still running, and the source
stays open afterwards so files can be previewed and saved.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from tizorecover.engine import allocation as alloc_mod
from tizorecover.engine import naming
from tizorecover.engine import tzscan
from tizorecover.engine import verify
from tizorecover.engine.access import CandidateData, pieces_of
from tizorecover.engine.blockdev import (BlockReader, DeviceBlockReader, DriveGoneError, VolumeAccessError,
                                         WindowBlockReader, open_source)
from tizorecover.engine.carver import carve_range
from tizorecover.engine.drives import Drive, list_drives
from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.partitions import PatchedReader
from tizorecover.engine.fs import exfat as exfat_fs
from tizorecover.engine.fs import ext4 as ext_fs
from tizorecover.engine.fs import fat as fat_fs
from tizorecover.engine.fs import ntfs as ntfs_fs
from tizorecover.engine.results import FileCandidate, Strategy
from tizorecover.engine.scan import detect_filesystem

QUICK = "quick"
DEEP = "deep"
MIN_FREE_RUN = 4096
AUTOSAVE_EVERY = 60.0


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
            "existing": bool(c.metadata.get("existing")),
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
        base = open_source(drive.path)
        reader: BlockReader = WindowBlockReader(base, drive.offset, drive.offset + drive.size,
                                                label=drive.id)
        if drive.boot_patch >= 0:
            # A file system whose first sectors were overwritten (a quick
            # format): read its surviving copy in their place.
            reader = PatchedReader(reader, base.read_at(drive.boot_patch, drive.patch_len))
        return reader
    return open_source(drive.path)


class ScanJob:
    """Runs one scan in the background and holds what it found."""

    def __init__(self, drive: Drive, mode: str = QUICK,
                 on_item: Callable[[Item], None] | None = None,
                 resume: dict | None = None, autosave: str | None = None, free_only: bool = True) -> None:
        self.drive = drive
        self.free_only = free_only            # False: the deep pass reads the whole volume, used space too
        self.mode = mode
        self.on_item = on_item
        self.resume = resume
        self.autosave = autosave
        self.fingerprint = ""
        self.quick_done = False
        self.deep_total = 0
        self.last_carve_end = 0
        self._saved_at = 0.0
        self.resumed_from = None
        self.state = "starting"
        self.filesystem = "unknown"
        self.progress = Progress()
        self.items: list[Item] = []
        self.problems: list[str] = []
        self.free_bytes = 0
        self.reader: BlockReader | None = None
        self.drive_gone = False
        self.paused = False
        self.list_existing = True
        self.existing_count = 0
        self.user_paused = False
        self._run_ev = threading.Event()
        self._run_ev.set()
        self.src: LockedSource | None = None
        self.allocation = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fs_starts: dict[int, Item] = {}
        self._carved_starts: dict[int, Item] = {}
        self.changed: list[int] = []          # ids of items replaced in place (the UI re-fetches them)
        self.loose = None                     # ntfs.LooseRecords the deep scan collects
        self._loose_offsets: list[int] = []   # from a saved scan, read again on resume
        self.ghosts: list[dict] = []          # names a folder index still remembers (NTFS $I30 slack)
        self._ghost_by_key: dict[tuple[int, str], dict] = {}
        self.thread = threading.Thread(target=self._run, name="tizo-scan", daemon=True)

    def start(self) -> "ScanJob":
        self.thread.start()
        return self

    def stop(self) -> None:
        """Stop now, even when the drive is sitting on a read: that read is cancelled."""
        self._stop.set()
        self._run_ev.set()
        dev = self._device()
        if dev is not None and hasattr(dev, "interrupt"):
            dev.interrupt()

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

    def changed_since(self, since: int) -> tuple[list[Item], int]:
        """Items replaced in place after the first ``since`` changes, and the change count now."""
        with self._lock:
            ids = self.changed[since:]
            return [self.items[i] for i in dict.fromkeys(ids)], len(self.changed)

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
                "free_bytes": self.free_bytes, "autosave": bool(self.autosave),
                "resumed_from": self.resumed_from, "bad_bytes": self.bad_bytes(),
                "drive_gone": self.drive_gone, "paused": self.paused, "user_paused": self.user_paused,
                "changed": len(self.changed)}

    def _device(self):
        """The raw device reader under any partition window or boot patch, if there is one."""
        r = self.reader
        for _ in range(6):
            if r is None or hasattr(r, "bad_bytes"):
                return r
            r = getattr(r, "parent", None)
        return None

    def bad_bytes(self) -> int:
        """Bytes the drive could not read (bad sectors), skipped and read as blank."""
        return int(getattr(self._device(), "bad_bytes", 0) or 0)

    def save(self, path: str | None = None) -> str | None:
        """Write this scan to ``path`` (default: its automatic save file)."""
        path = path or self.autosave
        if not path or not self.fingerprint:
            return None
        with self._lock:
            items = [{"status": it.status, "notes": it.notes, "category": it.category,
                      "candidate": tzscan.candidate_to_dict(it.candidate)} for it in self.items]
        deep_done = self.progress.done if self.progress.stage == "deep" else (
            self.deep_total if self.state == "done" and self.mode == DEEP else 0)
        if self.resume and self.progress.stage != "deep" and self.state != "done":
            deep_done = (self.resume.get("deep") or {}).get("done", 0)
        state = {
            "drive": self.drive.to_dict(), "fingerprint": self.fingerprint,
            "filesystem": self.filesystem, "mode": self.mode,
            "state": "running" if self.state in ("running", "starting") else self.state,
            "quick_done": self.quick_done, "problems": list(self.problems),
            "free_bytes": self.free_bytes,
            "deep": {"done": deep_done, "total": self.deep_total, "last_carve_end": self.last_carve_end,
                     "records": list(self.loose.offsets) if self.loose is not None else self._loose_offsets},
            "ghosts": self.ghosts,
            "items": items,
        }
        try:
            tzscan.save(path, state)
        except OSError as exc:
            self.problems.append(f"could not save the scan: {exc}")
            return None
        self._saved_at = time.time()
        return path

    def _maybe_autosave(self) -> None:
        if self.autosave and time.time() - self._saved_at > AUTOSAVE_EVERY:
            self.save()

    def close(self) -> None:
        self.stop()
        self.wait(5)
        if self.reader is not None:
            try:
                self.reader.close()
            except OSError:
                pass
            self.reader = None

    MAX_EXISTING = 300_000

    def _list_live(self) -> bool:
        """Live files are listed (Existing) on any drive but the Windows one, which can hold millions."""
        return self.drive.lost or (self.list_existing and not self.drive.system)

    def _set_ghosts(self, ghosts: list[dict]) -> None:
        """Keep the index leftovers whose size + type is unique: only those can be matched safely."""
        self.ghosts = ghosts
        counts: dict[tuple[int, str], int] = {}
        for g in ghosts:
            key = (int(g["size"]), (g.get("ext") or "").lower())
            counts[key] = counts.get(key, 0) + 1
        self._ghost_by_key = {(int(g["size"]), (g.get("ext") or "").lower()): g for g in ghosts
                              if g["size"] > 0 and counts[(int(g["size"]), (g.get("ext") or "").lower())] == 1}

    def _name_from_ghost(self, candidate: FileCandidate) -> bool:
        """A carved file whose exact size and type match one leftover index entry gets its name and folder back."""
        if not self._ghost_by_key:
            return False
        ext = (candidate.ext or "").lower()
        ext = {"jpeg": "jpg", "tiff": "tif"}.get(ext, ext)
        g = None
        for e in {ext, {"jpg": "jpeg", "tif": "tiff"}.get(ext, ext)}:
            g = self._ghost_by_key.pop((int(candidate.size), e), None)
            if g is not None:
                break
        if g is None:
            return False
        candidate.name = g["name"]
        candidate.original_path = g["path"]
        candidate.metadata["named_from"] = "ntfs-index"
        if g.get("modified") and not candidate.metadata.get("modified"):
            candidate.metadata["modified"] = g["modified"]
        candidate.reasons.append("name and folder from the folder's index (NTFS $I30 leftovers), "
                                 "matched by exact size and type")
        return True

    def _name_from_content(self, candidate: FileCandidate) -> None:
        """A carved file named by what it says about itself (EXIF date + camera, ID3, title...)."""
        data = CandidateData(candidate, self.src)
        try:
            name, ts = naming.describe(data.at, candidate.size, candidate.ext)
        except DriveGoneError:
            raise
        except Exception:  # noqa: BLE001 - a name is a bonus, never a reason to lose the file
            return
        if name:
            candidate.name = f"{name}.{(candidate.ext or 'bin').lower()}"
            candidate.metadata["named_from"] = "content"
        if ts and not candidate.metadata.get("modified"):
            candidate.metadata["modified"] = ts

    def _stage(self, name: str, total: int) -> None:
        self.progress.stage = name
        self.progress.done = 0
        self.progress.total = total
        self.progress.stage_started = time.time()

    def _advance(self, amount: int) -> None:
        self.progress.done += amount
        if self.progress.stage == "deep":
            self._maybe_autosave()
        if not self._run_ev.is_set():
            self._hold()

    def pause(self) -> None:
        """Hold the scan where it is (the drive is left alone) until resume() or stop()."""
        if self.state in ("running", "starting"):
            self._run_ev.clear()

    def resume_scan(self) -> None:
        self._run_ev.set()

    def _hold(self) -> None:
        stage, self.user_paused = self.progress.stage, True
        self.state = "paused"
        if self.autosave and self.items:
            self.save()
        started = time.time()
        while not self._run_ev.wait(0.3):
            if self._stop.is_set():
                break
        self.progress.stage_started += time.time() - started     # paused time is not scan time
        self.user_paused = False
        if not self._stop.is_set():
            self.state = "running"
            self.progress.stage = stage

    def _add(self, candidate: FileCandidate) -> None:
        if candidate.strategy is Strategy.CARVE:
            owner = self._fs_starts.get(candidate.data_offset)
            if owner is not None:
                note = f"confirmed by signature carving ({candidate.ext or '?'})"
                if note not in owner.candidate.reasons:
                    owner.candidate.reasons.append(note)
                return
        if candidate.metadata.get("loose_record"):
            first = pieces_of(candidate)[:1]
            if first and first[0][0] >= 0 and first[0][0] in self._fs_starts:
                return                        # the file table (or an earlier pass) already has this file
            if self._upgrade_carved(candidate):
                return
        existing = bool(candidate.metadata.get("live")) and not self.drive.lost
        if existing:
            self.existing_count += 1
            if self.existing_count > self.MAX_EXISTING:
                if self.existing_count == self.MAX_EXISTING + 1:
                    self.problems.append(f"Over {self.MAX_EXISTING:,} existing files: only the first ones are listed "
                                         f"(they are still on the drive anyway; the deleted ones are all here).")
                return
            candidate.metadata["existing"] = True
            status, notes = verify.GOOD, ["Not deleted: the file is still on the drive."]
        else:
            try:
                status, notes = verify.assess(candidate, self.src, self.allocation)
            except (OSError, ValueError) as exc:
                status, notes = verify.PARTIAL, [f"could not check: {exc}"]
        if candidate.strategy is Strategy.CARVE and not candidate.original_path:
            if not self._name_from_ghost(candidate):
                self._name_from_content(candidate)
        with self._lock:
            item = Item(len(self.items), candidate, status, notes,
                        verify.category_of(candidate.ext))
            self.items.append(item)
        self._index(item)
        if candidate.strategy is Strategy.CARVE:
            self._carved_starts.setdefault(candidate.data_offset, item)
            self.last_carve_end = max(self.last_carve_end, candidate.data_offset + candidate.size)
        if self.on_item is not None:
            self.on_item(item)

    def _upgrade_carved(self, candidate: FileCandidate) -> bool:
        """An old file record whose data is a file carving already found: give that item its name, folder, all pieces."""
        pieces = pieces_of(candidate)
        twin = self._carved_starts.get(pieces[0][0]) if pieces else None
        if twin is None or twin.candidate.strategy is not Strategy.CARVE or twin.candidate.size > candidate.size:
            return False
        candidate.reasons.append(f"also found by signature carving ({twin.candidate.ext or '?'})")
        try:
            status, notes = verify.assess(candidate, self.src, self.allocation)
        except (OSError, ValueError) as exc:
            status, notes = verify.PARTIAL, [f"could not check: {exc}"]
        with self._lock:
            twin.candidate, twin.status, twin.notes = candidate, status, notes
            twin.category = verify.category_of(candidate.ext)
            self.changed.append(twin.id)
        del self._carved_starts[pieces[0][0]]
        self._index(twin)
        if self.on_item is not None:
            self.on_item(twin)
        return True

    def _loose_records_found(self) -> None:
        """Add the files the old MFT records describe (deep scan of an NTFS volume, at its end)."""
        if self.loose is None:
            return
        for offset in self._loose_offsets:           # found before a save this scan resumed from
            self.loose.add(offset, self.src.at(offset, 4096))
        self._loose_offsets = []
        for cand in self.loose.candidates(self.src, self.drive.id):
            self._add(cand)

    def _pause_until_back(self, exc: Exception) -> bool:
        """The drive went away mid-scan. Save, wait for it (or Stop), reopen it, resume in place.

        True: it is back and the scan continues. False: Stop was pressed while waiting.
        The same drive is recognised by its fingerprint, not its letter or disk number,
        which can both change when it is plugged in again.
        """
        log = logging.getLogger("tizorecover")
        log.warning("drive gone during scan of %s: %s -- pausing", self.drive.path, exc)
        deep_done = self.progress.done if self.progress.stage == "deep" else 0
        stage = self.progress.stage
        if self.autosave and self.items:
            self.save()
        self.paused = True
        self.state = "paused"
        self.progress.stage = "paused"
        old = self.reader
        self.reader = None
        try:
            if old is not None:
                old.close()
        except OSError:
            pass
        while not self._stop.wait(3.0):
            fresh = self._find_again()
            if fresh is None:
                continue
            drive, reader = fresh
            log.info("drive back as %s, scan continues", drive.path)
            self.drive = drive
            self.reader = reader
            self.src = LockedSource(ByteSourceView(reader))
            self.paused = False
            self.state = "running"
            if not self.quick_done:
                self._forget_quick_items()        # the quick pass runs again from the start
                self._stage("records", 0)
            else:
                self.resume = {**(self.resume or {}), "mode": DEEP, "deep": {"done": deep_done}}
                self.progress.stage = stage
            return True
        self.paused = False
        return False

    def _find_again(self):
        """(drive, reader) when the drive this scan was reading is back, else None."""
        d = self.drive
        try:
            if d.kind == "image":
                options = [d] if os.path.exists(d.path) else []
            else:
                options = [x for x in list_drives() if x.size == d.size and x.kind == d.kind
                           and x.partition == d.partition and (x.disk_name == d.disk_name or not d.disk_name)]
        except Exception:  # noqa: BLE001 - listing drives can fail while Windows re-enumerates
            return None
        for cand in options:
            if d.lost:
                cand = d.__class__(**{**d.to_dict(), "path": cand.path if cand.kind != "image" else d.path})
            try:
                reader = open_drive(cand)
            except (OSError, VolumeAccessError):
                continue
            try:
                same = tzscan.fingerprint(LockedSource(ByteSourceView(reader))) == self.fingerprint
            except OSError:
                same = False
            if same:
                return cand, reader
            try:
                reader.close()
            except OSError:
                pass
        return None

    def _forget_quick_items(self) -> None:
        with self._lock:
            self.items = []
        self._fs_starts = {}

    def _index(self, item: Item) -> None:
        pieces = pieces_of(item.candidate)
        if item.candidate.strategy is not Strategy.CARVE and pieces and pieces[0][0] >= 0:
            self._fs_starts.setdefault(pieces[0][0], item)

    def _load_resume(self) -> bool:
        """Take over a saved scan's results. False when the drive is not the same one."""
        saved = self.resume
        if saved.get("fingerprint") != self.fingerprint:
            self.problems.append("This saved scan belongs to a different drive, or the drive has "
                                 "changed since (it was formatted, or written to). Start a new scan.")
            return False
        if not saved.get("quick_done"):
            # Stopped inside the quick pass: it is fast, run it all again.
            self.resume = {**saved, "items": [], "deep": {}, "state": "stopped"}
            self.resumed_from = saved.get("saved_at")
            return True
        with self._lock:
            for i, raw in enumerate(saved.get("items", [])):
                cand = tzscan.candidate_from_dict(raw["candidate"])
                self.items.append(Item(i, cand, raw["status"], list(raw.get("notes", [])),
                                       raw.get("category") or verify.category_of(cand.ext)))
        for item in self.items:
            self._index(item)
        self.quick_done = bool(saved.get("quick_done"))
        self.last_carve_end = int((saved.get("deep") or {}).get("last_carve_end") or 0)
        self._loose_offsets = [int(o) for o in (saved.get("deep") or {}).get("records") or []]
        self.resumed_from = saved.get("saved_at")
        used = {it.candidate.original_path for it in self.items if it.candidate.original_path}
        self._set_ghosts([g for g in saved.get("ghosts") or [] if g.get("path") not in used])
        return True

    def _run(self) -> None:
        self.state = "running"
        try:
            self._stage("opening", 0)
            self.reader = open_drive(self.drive)
            self.src = LockedSource(ByteSourceView(self.reader))
            self.fingerprint = tzscan.fingerprint(self.src)
            self.filesystem = detect_filesystem(self.src)
            # A lost volume's own bitmap marks its files "in use", which says
            # nothing about whether the space's current owner wrote over them,
            # and its free space is not where its files are: no map for it.
            self.allocation = None if self.drive.lost else alloc_mod.detect(self.src, self.filesystem)
            if self.allocation is not None:
                self.free_bytes = self.allocation.free_bytes
            if self.resume is not None:
                if not self._load_resume():
                    self.autosave = None          # never overwrite the other drive's save
                    self.state = "failed"
                    self.progress.stage = self.state
                    return
                if self.resume.get("state") == "done" and (self.mode == QUICK or
                                                           self.resume.get("mode") == DEEP):
                    self.state = "done"
                    self.progress.stage = "done"
                    return
            while True:
                try:
                    if not self.quick_done:
                        self._quick()
                        self.quick_done = not self.stopping
                    if self.mode == DEEP and not self.stopping:
                        self._deep()
                    break
                except DriveGoneError as exc:
                    # Pause, don't fail: wait for the same drive to come back and carry on from here.
                    if not self._pause_until_back(exc):
                        break
            self.state = "stopped" if self.stopping else "done"
        except VolumeAccessError as exc:
            self.problems.append(str(exc))
            self.state = "failed"
        except DriveGoneError as exc:
            logging.getLogger("tizorecover").warning("drive gone during scan of %s: %s", self.drive.path, exc)
            self.drive_gone = True
            self.problems.append("The drive disconnected while it was being opened. Plug it back in, then "
                                 "choose Resume (or start the scan again).")
            self.state = "failed"
        except Exception as exc:  # the UI must hear about it, whatever it is
            logging.getLogger("tizorecover").exception("scan of %s failed", self.drive.path)
            self.problems.append(f"scan failed: {exc!r}")
            self.state = "failed"
        dev = self._device()
        if dev is not None and hasattr(dev, "resume"):
            dev.resume()                      # previews and recovery read normally again
        if self.autosave and self.items and (self.state in ("done", "stopped") or self.drive_gone):
            self.save()
        bad = self.bad_bytes()
        if bad:
            self.problems.append(f"{bad // 1024:,} KB of the drive could not be read (bad sectors) and was skipped. "
                                 f"Files that lie there may be damaged; the drive may be failing, so copy what you "
                                 f"need off it soon.")
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
            ghosts: list[dict] = []
            for cand in ntfs_fs.recover_ntfs(self.src, self.drive.id, progress=self._advance,
                                             should_stop=stop, include_live=self._list_live(), ghosts=ghosts):
                self._add(cand)
            self._set_ghosts(ghosts)
            if not self.stopping:
                self.progress.done = self.progress.total
        elif fs in ("fat", "fat32"):
            self._stage("records", 0)
            for cand in fat_fs.recover_fat(self.src, self.drive.id, progress=self._advance,
                                           should_stop=stop, include_live=self._list_live()):
                self._add(cand)
        elif fs == "exfat":
            self._stage("records", 0)
            for cand in exfat_fs.recover_exfat(self.src, self.drive.id, progress=self._advance,
                                               should_stop=stop, include_live=self._list_live()):
                self._add(cand)
        elif fs.startswith("ext"):
            self._stage("records", 0)
            for cand in ext_fs.recover_ext(self.src, self.drive.id, progress=self._advance,
                                           should_stop=stop, include_live=self._list_live()):
                self._add(cand)
        else:
            self.problems.append(f"No readable filesystem ({fs}). Run a deep scan to find "
                                 f"files by their content.")

    def _deep(self) -> None:
        if self.allocation is not None and self.free_only:
            ranges = list(self.allocation.free_ranges(MIN_FREE_RUN))
        else:
            ranges = [(0, self.src.size)]
            if self.filesystem not in ("unknown",):
                self.problems.append("Could not read which space is free, so the deep scan "
                                     "reads the whole drive and may also list files that "
                                     "still exist.")
        self.deep_total = sum(n for _o, n in ranges)
        self._stage("deep", self.deep_total)
        skip = 0
        if self.resume is not None and self.resume.get("mode") == DEEP:
            skip = min(int((self.resume.get("deep") or {}).get("done") or 0), self.deep_total)
            self.progress.done = skip
        stop = self._stop.is_set
        on_record = None
        if self.filesystem == "ntfs":
            if self.loose is None:
                boot = ntfs_fs.parse_boot_sector(self.src)
                self.loose = ntfs_fs.LooseRecords(boot) if boot is not None else None
                if self.loose is not None and not self.drive.lost:
                    self.loose.exclude_mft(self.src)
                    size = self.loose.boot.mft_record_size
                    for off in self.loose.slack:          # allocated, so the free-space pass never reads it
                        self.loose.add(off, self.src.at(off, size))
            if self.loose is not None:
                on_record = self.loose.add
        elif self.filesystem in ("fat", "fat32", "fat12", "fat16"):
            # Lost folders (TestDisk's method): their "." / ".." first entries lie in free space.
            if self.loose is None:
                info = fat_fs.find_fat(self.src)
                self.loose = fat_fs.LooseDirs(self.src, info) if info is not None else None
            if self.loose is not None:
                on_record = self.loose.add
        for offset, length in ranges:
            if stop():
                break
            if skip >= length:
                skip -= length
                continue
            start = offset + skip
            skip = 0
            if self.last_carve_end > start:
                # A file found just before the save runs on past the cut.
                moved = min(self.last_carve_end, offset + length) - start
                start += moved
                self.progress.done += moved
            if start >= offset + length:
                continue
            for cand in carve_range(self.src, self.drive.id, start=start, end=offset + length,
                                    progress=self._advance, should_stop=stop, on_record=on_record):
                self._add(cand)
        self._loose_records_found()
