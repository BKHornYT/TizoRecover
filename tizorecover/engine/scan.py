"""Runs every recovery strategy against one volume and merges the results.

The strategies are independent and deliberately redundant: a filesystem
parser knows the original name and path but only finds files whose metadata
survived, while carving finds orphaned bytes but knows nothing about names.
Running both and merging gives the best of each, and the report keeps every
claim so a file that only one strategy found is still shown.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Iterable

import hashlib

from .blockdev import BlockReader, VolumeAccessError, open_source, resolve_volume
from .carver import carve_orphans, carve_range
from .formats import ByteSourceView
from .fs import fat as fat_fs
from .fs import ntfs as ntfs_fs
from .results import FileCandidate, RecoveryReport, Strategy, Verdict

Handler = Callable[[ByteSourceView, str, Callable[[int], None] | None,
                    Callable[[], bool] | None], Iterable[FileCandidate]]


def detect_filesystem(src: ByteSourceView) -> str:
    """Name the filesystem from its superblock, or ``unknown``."""
    if ntfs_fs.parse_boot_sector(src) is not None:
        return "ntfs"
    if fat_fs.find_fat(src) is not None:
        head = src.at(0, 512)
        if head[0x52:0x5A] == b"FAT32   ":
            return "fat32"
        if head[0x36:0x3E] == b"EXFAT   ":
            return "exfat"
        return "fat"
    magic = src.at(0x438, 2)
    if magic == b"\x53\xef":
        return "ext2/3/4"
    return "unknown"


def _ntfs_handler(src, volume, progress, should_stop, on_found=None):
    return ntfs_fs.recover_ntfs(src, volume, progress=progress, should_stop=should_stop)


def _fat_handler(src, volume, progress, should_stop, on_found=None):
    return fat_fs.recover_fat(src, volume, progress=progress, should_stop=should_stop)


def _carve_handler(src, volume, progress, should_stop, on_found=None):
    return carve_range(src, volume, progress=progress, should_stop=should_stop,
                       on_found=on_found)


def _orphan_handler(src, volume, progress, should_stop, on_found=None):
    return carve_orphans(src, volume, progress=progress, should_stop=should_stop,
                         on_found=on_found)


def _is_exfat(src: ByteSourceView) -> bool:
    return src.at(0, 512)[0x36:0x3E] == b"EXFAT   "


def scan(
    folder: str,
    strategies: Iterable[str] | None = None,
    chunk: int = 8 << 20,
    include_orphans: bool = True,
    progress: Callable[[str, int], None] | None = None,
    on_candidate: Callable[["Strategy", int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RecoveryReport:
    """Recover from the volume holding ``folder``.

    ``progress`` receives ``(stage, bytes_done)`` so a caller can drive a
    progress bar; ``should_stop`` is polled between chunks.
    """
    try:
        device, _hint, size = resolve_volume(folder)
    except VolumeAccessError as exc:
        report = RecoveryReport(target=folder, volume="", filesystem="unknown",
                                volume_size=0)
        report.problem(Strategy.CARVE, str(exc), fatal=True)
        return report
    return scan_device(device, target=folder, strategies=strategies, chunk=chunk,
                       include_orphans=include_orphans, progress=progress,
                       should_stop=should_stop)


def scan_device(
    device: str,
    target: str | None = None,
    strategies: Iterable[str] | None = None,
    chunk: int = 8 << 20,
    include_orphans: bool = True,
    progress: Callable[[str, int], None] | None = None,
    on_candidate: Callable[["Strategy", int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RecoveryReport:
    """Recover from a block device or disk image file."""
    volume = os.path.basename(device.rstrip("/\\")) or device
    report = RecoveryReport(target=target or device, volume=volume,
                            filesystem="unknown", volume_size=0, device=device)
    started = time.time()
    wanted = set(strategies) if strategies else {"ntfs", "fat", "carve"}
    # An explicit list is an explicit list: naming ntfs alone must not drag in
    # the footer-first pass just because --no-orphans was left at its default.
    if include_orphans and not strategies:
        wanted.add("orphans")

    reader: BlockReader | None = None
    try:
        reader = open_source(device)
        src = ByteSourceView(reader)
        filesystem = detect_filesystem(src)
        report.filesystem = filesystem
        report.volume_size = reader.size or size

        if _is_exfat(src):
            report.problem(
                Strategy.FAT,
                "exFAT detected: exFAT has no FAT chain left to walk once a file "
                "is deleted, so only carving can recover names-less copies",
            )

        handlers: list[tuple[str, Handler]] = []
        if "ntfs" in wanted:
            handlers.append(("ntfs", _ntfs_handler))
        if "fat" in wanted and filesystem in ("fat", "fat32", "exfat"):
            handlers.append(("fat", _fat_handler))
        if "carve" in wanted:
            handlers.append(("carve", _carve_handler))
        if "orphans" in wanted:
            handlers.append(("orphans", _orphan_handler))

        for name, handler in handlers:
            if should_stop is not None and should_stop():
                break
            strategy = {"ntfs": Strategy.NTFS, "fat": Strategy.FAT,
                        "carve": Strategy.CARVE, "orphans": Strategy.CARVE}[name]
            if name in ("ntfs", "fat") and filesystem == "unknown":
                report.problem(strategy, f"no {name.upper()} superblock found; skipped")
                continue
            if name == "ntfs" and filesystem not in ("ntfs", "unknown"):
                report.problem(strategy,
                               f"volume is {filesystem}, not NTFS; NTFS pass skipped")
                continue
            if name == "fat" and filesystem not in ("fat", "fat32", "exfat"):
                report.problem(strategy,
                               f"volume is {filesystem}, not FAT; FAT pass skipped")
                continue
            if name == "fat" and filesystem == "exfat":
                report.problem(strategy, "exFAT directory parsing is not implemented; "
                                         "falling back to carving")
                continue

            def on_progress(amount: int, _name: str = name) -> None:
                if progress is not None:
                    progress(_name, amount)

            if progress is not None:
                progress(name, 0)
            def on_found(_cand, _strategy=strategy) -> None:
                if on_candidate is not None:
                    on_candidate(_strategy, len(report.candidates) + 1)

            try:
                for candidate in handler(src, volume, on_progress, should_stop,
                                         on_found):
                    report.add(candidate)
                    if on_candidate is not None:
                        on_candidate(strategy, len(report.candidates))
            except (OSError, MemoryError) as exc:
                report.problem(strategy, f"{name} pass stopped early: {exc}", fatal=True)
            except Exception as exc:
                report.problem(strategy, f"{name} pass failed: {exc!r}", fatal=True)

        merge(report)
    except VolumeAccessError as exc:
        report.problem(Strategy.CARVE, str(exc), fatal=True)
    finally:
        if reader is not None:
            reader.close()

    report.bytes_scanned = report.volume_size
    report.elapsed = time.time() - started
    return report


def _fingerprint(candidate: FileCandidate) -> tuple:
    """Identity used to decide that two claims are the same file."""
    if candidate.content_hash:
        return ("hash", candidate.content_hash)
    if candidate.original_path and candidate.size:
        return ("path", candidate.original_path, candidate.size)
    return ("offset", candidate.data_offset, candidate.size, candidate.ext)


def merge(report: RecoveryReport) -> None:
    """Collapse claims that describe the same file, keeping the best one.

    A filesystem hit beats a carve hit for the same bytes: it has the real
    name and path. Conflicting names for one fingerprint are reported as a
    problem rather than silently resolved.
    """
    order = {Strategy.NTFS: 0, Strategy.FAT: 1, Strategy.EXT4: 2,
             Strategy.CARVE: 3, Strategy.LIVE: 4}
    best: dict[tuple, FileCandidate] = {}
    merged: list[FileCandidate] = []
    # A carved hit that starts where a filesystem hit's first extent starts is
    # the same file found twice; the filesystem hit wins because it has the
    # real name. Only the start is compared: the carver measures the file from
    # its own structure, so its size can differ from the recorded one.
    starts: dict[int, FileCandidate] = {}
    for candidate in report.candidates:
        if candidate.strategy in (Strategy.NTFS, Strategy.FAT, Strategy.EXT4):
            extents = candidate.metadata.get("extents") or []
            if extents and extents[0][0] >= 0:
                starts.setdefault(extents[0][0], candidate)
    for candidate in report.candidates:
        if candidate.strategy is Strategy.CARVE and candidate.data_offset in starts:
            owner = starts[candidate.data_offset]
            note = f"confirmed by signature carving ({candidate.ext or '?'})"
            if note not in owner.reasons:
                owner.reasons.append(note)
            owner.confidence = min(0.99, owner.confidence + 0.05)
            continue
        if candidate.content_hash is None:
            inline = candidate.metadata.get("inline_data")
            if inline:
                candidate.content_hash = hashlib.sha256(inline).hexdigest()
        key = _fingerprint(candidate)
        winner = best.get(key)
        if winner is None:
            best[key] = candidate
            merged.append(candidate)
            continue
        if order.get(candidate.strategy, 9) < order.get(winner.strategy, 9):
            best[key] = candidate
            merged[merged.index(winner)] = candidate
            winner = candidate
        for reason in candidate.reasons:
            if reason not in winner.reasons:
                winner.reasons.append(reason)
        if candidate.content_hash and not winner.content_hash:
            winner.content_hash = candidate.content_hash
        if candidate.original_path and not winner.original_path:
            winner.original_path = candidate.original_path
        winner.confidence = min(0.99, max(winner.confidence, candidate.confidence))
    report.candidates = merged
    for candidate in report.candidates:
        if candidate.verdict is Verdict.SUSPECT and candidate.confidence >= 0.7:
            candidate.verdict = Verdict.VALID
    return merged
