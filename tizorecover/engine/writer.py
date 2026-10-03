"""Saves recovered candidates to disk under safe, unique names."""

from __future__ import annotations

import os
import re
import time
import hashlib

from .access import pieces_of, read_all
from .blockdev import open_source
from .formats import ByteSourceView
from .results import FileCandidate, RecoveryReport, Strategy

_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')
_SEPARATORS = re.compile(r"[/\\]")
_DOTS_ONLY = re.compile(r"^\.+$")
_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME = 120


def safe_component(name: str) -> str:
    """Make one path component safe on Windows, macOS and Linux.

    A component made only of dots would climb out of the output folder, and
    separators would split one name into several, so both are removed rather
    than escaped.
    """
    name = _SEPARATORS.sub("_", _ILLEGAL.sub("_", name))
    if _DOTS_ONLY.match(name):
        return "_"
    name = name.strip().rstrip(". ")
    if not name:
        return "_"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    stem = stem[:MAX_NAME - len(ext) - 1] if ext else stem[:MAX_NAME]
    return f"{stem}.{ext}" if ext else stem


def safe_path(original: str | None, fallback: str) -> str:
    parts = [safe_component(p) for p in (original or "").replace("\\", "/").split("/") if p]
    if not parts:
        parts = [safe_component(fallback)]
    return os.path.join(*parts)


def _read_bytes(candidate: FileCandidate, source_path: str | None) -> bytes:
    data = candidate.metadata.get("inline_data")
    if data is not None:
        return data
    if not source_path or not pieces_of(candidate):
        return b""
    with open_source(source_path) as reader:
        return read_all(candidate, ByteSourceView(reader))


def unique_path(directory: str, name: str, used: set[str]) -> str:
    """Return a path inside ``directory`` that is not already taken."""
    candidate = os.path.join(directory, name)
    if candidate not in used and not os.path.exists(candidate):
        used.add(candidate)
        return candidate
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    index = 1
    while True:
        numbered = f"{stem} ({index}).{ext}" if ext else f"{stem} ({index})"
        candidate = os.path.join(directory, numbered)
        if candidate not in used and not os.path.exists(candidate):
            used.add(candidate)
            return candidate
        index += 1


def save(
    report: RecoveryReport,
    out_dir: str,
    min_confidence: float = 0.0,
    preserve_paths: bool = True,
    source_path: str | None = None,
    should_stop=None,
) -> list[tuple[FileCandidate, str, bool]]:
    """Write every candidate above ``min_confidence``.

    Returns ``(candidate, written_path, ok)`` for each one attempted. Files
    whose original folder structure is known are rebuilt under ``out_dir``;
    carved files land in a flat ``carved`` folder.
    """
    os.makedirs(out_dir, exist_ok=True)
    used: set[str] = set()
    seen_hashes: dict[str, FileCandidate] = {}
    duplicates: list[FileCandidate] = []
    written: list[tuple[FileCandidate, str, bool]] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    source = source_path or report.device or None

    ordered = sorted(report.candidates,
                     key=lambda c: (0 if c.original_path else 1, -c.confidence))
    for candidate in ordered:
        if should_stop is not None and should_stop():
            break
        if candidate.confidence < min_confidence:
            continue
        try:
            data = _read_bytes(candidate, source)
        except OSError as exc:
            written.append((candidate, "", False))
            report.problem(candidate.strategy, f"could not read candidate data: {exc}")
            continue
        if not data:
            written.append((candidate, "", False))
            report.problem(candidate.strategy, "no data available for candidate")
            continue
        digest = hashlib.sha256(data).hexdigest()
        candidate.content_hash = digest
        first = seen_hashes.get(digest)
        if first is not None:
            duplicates.append(candidate)
            continue
        seen_hashes[digest] = candidate
        if preserve_paths and candidate.original_path:
            relative = safe_path(candidate.original_path,
                                 f"recovered_{candidate.data_offset:012x}.{candidate.ext or 'bin'}")
        else:
            fallback = (candidate.name
                        or f"recovered_{candidate.data_offset:012x}.{candidate.ext or 'bin'}")
            if candidate.ext and not fallback.endswith(f".{candidate.ext}"):
                fallback = f"{fallback}.{candidate.ext}"
            relative = os.path.join("carved", safe_component(fallback))
        target = unique_path(out_dir, relative, used)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with open(target, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            written.append((candidate, target, False))
            report.problem(candidate.strategy, f"could not write {target}: {exc}")
            continue
        written.append((candidate, target, True))

    if duplicates:
        dropped = {id(c) for c in duplicates}
        report.candidates = [c for c in report.candidates if id(c) not in dropped]
        report.problem(Strategy.CARVE,
                       f"{len(duplicates)} duplicate(s) dropped: same content as a "
                       f"higher-confidence result")

    with open(os.path.join(out_dir, f"recovery-{stamp}.txt"), "w", encoding="utf-8") as handle:
        handle.write(report.summary())
        handle.write("\n\n")
        for candidate, path, ok in written:
            handle.write(f"{'saved' if ok else 'FAILED'}  {path}\n")
            handle.write(f"        {candidate.describe()}\n")
    return written


def save_items(
    items,
    data_for,
    out_dir: str,
    keep_folders: bool = True,
    progress=None,
    should_stop=None,
) -> list[tuple[object, str, bool, str]]:
    """Stream each chosen item to ``out_dir``; never overwrite anything.

    ``items`` are scan items (``.candidate``, ``.category``); ``data_for(item)``
    returns its :class:`~tizorecover.engine.access.CandidateData`. Named files
    land under their original folder, files found by content under
    ``Found by content/<category>``. ``progress(bytes)`` is called as data is
    written. Returns ``(item, path, ok, error)`` per item.
    """
    os.makedirs(out_dir, exist_ok=True)
    used: set[str] = set()
    results = []
    for item in items:
        if should_stop is not None and should_stop():
            break
        c = item.candidate
        fallback = c.name or f"recovered_{max(c.data_offset, 0):012x}.{c.ext or 'bin'}"
        if c.original_path and keep_folders:
            relative = safe_path(c.original_path, fallback)
        elif c.original_path:
            relative = safe_component(c.name or fallback)
        else:
            relative = os.path.join("Found by content", item.category.capitalize(),
                                    safe_component(fallback))
        target = unique_path(out_dir, relative, used)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                for block in data_for(item).chunks():
                    if should_stop is not None and should_stop():
                        break
                    handle.write(block)
                    if progress is not None:
                        progress(len(block))
            modified = c.metadata.get("modified")
            if modified:
                try:
                    os.utime(target, (modified, modified))
                except (OSError, OverflowError, ValueError):
                    pass
            results.append((item, target, True, ""))
        except OSError as exc:
            results.append((item, target, False, str(exc)))
    return results
