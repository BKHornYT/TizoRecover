"""Saved scans (``.tzscan``): stop a long scan, come back to it later.

A deep scan of a big hard drive takes hours, so the job writes its state
here every minute and when it stops: what it found (with each file's status,
so nothing is checked again) and how far the content search got. Resuming
loads the files and carves on from that point; a finished scan reopens
instantly. The drive must still be the same one: a fingerprint of its first
sector (which holds the volume serial number) is compared before anything is
trusted.

The file is gzip-compressed JSON. Small files kept inside a filesystem
record travel along as base64; everything else is only offsets, so a saved
scan is useless without the drive itself and holds no file contents.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time

from tizorecover import __version__
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

MAGIC = "tizorecover-scan"
VERSION = 1
SUFFIX = ".tzscan"


def sessions_dir() -> str:
    """Where automatic saves live (per user)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    path = os.path.join(base, "TizoRecover", "scans")
    os.makedirs(path, exist_ok=True)
    return path


def drive_key(drive) -> str:
    """A stable file name for a drive's automatic save."""
    raw = f"{drive.id}|{drive.size}|{drive.disk_name}|{drive.path if drive.kind == 'image' else ''}"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{drive.letter or ''} {drive.label or drive.disk_name}").strip("-")
    return f"{slug[:40] or 'drive'}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def auto_path(drive) -> str:
    return os.path.join(sessions_dir(), drive_key(drive) + SUFFIX)


def fingerprint(src) -> str:
    """Hash of the first sector plus the size: the same volume, not just the same letter."""
    head = src.at(0, 512) if src.size else b""
    return hashlib.sha256(head + str(src.size).encode()).hexdigest()[:32]


def _encode_meta(meta: dict) -> dict:
    out = {}
    for key, value in meta.items():
        if isinstance(value, (bytes, bytearray, memoryview)):
            out[key] = {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
        else:
            out[key] = value
    return out


def _decode_meta(meta: dict) -> dict:
    out = {}
    for key, value in meta.items():
        if isinstance(value, dict) and "__b64__" in value:
            out[key] = base64.b64decode(value["__b64__"])
        else:
            out[key] = value
    return out


def candidate_to_dict(c: FileCandidate) -> dict:
    return {
        "ext": c.ext, "size": c.size, "data_offset": c.data_offset, "strategy": c.strategy.value,
        "name": c.name, "original_path": c.original_path, "verdict": c.verdict.value,
        "confidence": c.confidence, "reasons": list(c.reasons), "volume": c.volume,
        "fragment_index": c.fragment_index, "fragment_count": c.fragment_count,
        "gaps": [list(g) for g in c.gaps], "content_hash": c.content_hash,
        "metadata": _encode_meta(c.metadata),
    }


def candidate_from_dict(d: dict) -> FileCandidate:
    return FileCandidate(
        ext=d["ext"], size=int(d["size"]), data_offset=int(d["data_offset"]),
        strategy=Strategy(d["strategy"]), name=d.get("name"), original_path=d.get("original_path"),
        verdict=Verdict(d.get("verdict", "suspect")), confidence=float(d.get("confidence", 0)),
        reasons=list(d.get("reasons", [])), volume=d.get("volume", ""),
        fragment_index=int(d.get("fragment_index", 0)), fragment_count=int(d.get("fragment_count", 1)),
        gaps=[tuple(g) for g in d.get("gaps", [])], content_hash=d.get("content_hash"),
        metadata=_decode_meta(d.get("metadata", {})),
    )


def save(path: str, state: dict) -> None:
    """Write atomically: a crash mid-save never leaves a broken file behind."""
    body = dict(state)
    body.update({"format": MAGIC, "version": VERSION, "app": __version__, "saved_at": time.time()})
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tzscan-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=5) as gz:
            gz.write(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        os.replace(tmp, path)
        with open(path + ".info", "w", encoding="utf-8") as fh:
            json.dump(_summary_of(body, path), fh)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load(path: str) -> dict:
    with gzip.open(path, "rb") as gz:
        body = json.loads(gz.read().decode("utf-8"))
    if body.get("format") != MAGIC:
        raise ValueError("not a TizoRecover scan file")
    if int(body.get("version", 0)) > VERSION:
        raise ValueError("this scan was saved by a newer TizoRecover; update to open it")
    return body


def summary(path: str) -> dict | None:
    """What the UI shows about a saved scan (from its small ``.info`` twin when there is one)."""
    try:
        with open(path + ".info", encoding="utf-8") as fh:
            info = json.load(fh)
        info["path"] = path
        return info
    except (OSError, ValueError):
        pass
    try:
        body = load(path)
    except (OSError, ValueError, EOFError, json.JSONDecodeError):
        return None
    return _summary_of(body, path)


def _summary_of(body: dict, path: str) -> dict:
    deep = body.get("deep") or {}
    total = deep.get("total") or 0
    return {
        "path": path, "drive": body.get("drive", {}), "mode": body.get("mode"),
        "state": body.get("state"), "saved_at": body.get("saved_at"),
        "found": len(body.get("items", [])), "filesystem": body.get("filesystem"),
        "found_bytes": sum(int(i["candidate"]["size"]) for i in body.get("items", [])),
        "deep_pct": round(100 * deep.get("done", 0) / total, 1) if total else (100.0 if body.get("state") == "done" else 0.0),
    }


def list_saved() -> list[dict]:
    out = []
    try:
        names = os.listdir(sessions_dir())
    except OSError:
        return out
    for name in names:
        if name.endswith(SUFFIX) and not name.startswith("."):
            info = summary(os.path.join(sessions_dir(), name))
            if info is not None:
                out.append(info)
    out.sort(key=lambda s: s.get("saved_at") or 0, reverse=True)
    return out
