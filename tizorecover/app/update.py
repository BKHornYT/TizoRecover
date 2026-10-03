"""Checking GitHub Releases for a newer TizoRecover, and installing it.

Releases carry the same ``latest.yml`` / ``latest-linux.yml`` feeds that
electron-builder writes for the other Tizo apps: version, file name, SHA-512
(base64) and size. An installed copy (it has the installer's ``.installed``
marker next to it) can download the new setup, check its hash and run it; a
portable copy or a source checkout only gets a link to the release page.
Only the version feed is fetched, nothing about the user is sent.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request

from tizorecover import __version__

REPO = "BKHornYT/TizoRecover"
FEED = f"https://github.com/{REPO}/releases/latest/download/" + \
    ("latest.yml" if sys.platform == "win32" else "latest-linux.yml")
PAGE = f"https://github.com/{REPO}/releases/latest"
TIMEOUT = 8


def parse_feed(text: str) -> dict:
    """The few top-level keys of an electron-builder feed (no YAML library needed)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(version|path|sha512|releaseDate):\s*'?([^']*?)'?\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    m = re.search(r"^\s+size:\s*(\d+)", text, re.M)
    if m:
        out["size"] = int(m.group(1))
    return out


def _parts(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3])


def newer(remote: str, local: str = __version__) -> bool:
    try:
        return _parts(remote) > _parts(local)
    except ValueError:
        return False


def installed() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    return os.path.exists(os.path.join(os.path.dirname(sys.executable), ".installed"))


class Updater:
    def __init__(self) -> None:
        self.state = {"state": "idle", "current": __version__}
        self.feed: dict = {}

    def check(self) -> dict:
        try:
            req = urllib.request.Request(FEED, headers={"User-Agent": f"TizoRecover/{__version__}"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                self.feed = parse_feed(r.read(64 << 10).decode("utf-8", "replace"))
        except Exception as exc:
            return {"available": False, "current": __version__, "error": str(exc)}
        version = self.feed.get("version", "")
        return {"available": bool(version) and newer(version), "version": version,
                "current": __version__, "page": PAGE,
                "can_install": installed() and sys.platform == "win32" and bool(self.feed.get("path"))}

    def install(self) -> dict:
        if not (installed() and sys.platform == "win32" and self.feed.get("path")):
            return {"error": "Only an installed copy can update itself. Download the new version "
                             "from the release page."}
        if self.state.get("state") == "downloading":
            return {"ok": True}
        self.state = {"state": "downloading", "done": 0, "total": self.feed.get("size", 0)}
        threading.Thread(target=self._download, daemon=True).start()
        return {"ok": True}

    def _download(self) -> None:
        name = os.path.basename(self.feed["path"])
        url = f"https://github.com/{REPO}/releases/download/v{self.feed['version']}/{name}"
        target = os.path.join(tempfile.gettempdir(), name)
        digest = hashlib.sha512()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"TizoRecover/{__version__}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(target, "wb") as fh:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    fh.write(block)
                    digest.update(block)
                    self.state["done"] += len(block)
            want = self.feed.get("sha512", "")
            if want and base64.b64encode(digest.digest()).decode() != want:
                os.unlink(target)
                self.state = {"state": "failed", "error": "The download did not match its checksum."}
                return
            self.state = {"state": "installing"}
            # /UPDATE=1 makes the installer start the new version when it is done.
            subprocess.Popen([target, "/SP-", "/SILENT", "/NOCANCEL", "/UPDATE=1"],
                             close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            threading.Timer(1.5, lambda: os._exit(0)).start()
        except Exception as exc:
            self.state = {"state": "failed", "error": str(exc)}
