"""The local HTTP API the window talks to.

The UI is a web page, so the engine is put behind a tiny HTTP server bound
to 127.0.0.1 on a random port. Every API call must carry the per-run token
(header ``X-Tizo-Token`` or ``?t=`` for media elements, which cannot send
headers), so no other local program or web page can drive it. Byte ranges
are served for previews, which is what lets a recovered video seek without
being read whole.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tizorecover import APP_NAME, __version__
from tizorecover.engine import drives as drives_mod
from tizorecover.engine.erase import EraseError, EraseJob, Planner
from tizorecover.engine import formats as formats_mod
from tizorecover.engine import partitions as parts_mod
from tizorecover.engine import tzscan
from tizorecover.engine import fixdrive
from tizorecover.engine.eject import EjectError, eject as eject_disk
from tizorecover.engine.blockdev import VolumeAccessError, open_source
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tizorecover.engine.writer import save_items
from tizorecover.app import crashlog
from tizorecover.app.update import Updater

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if getattr(sys, "frozen", False):
    WEB = os.path.join(getattr(sys, "_MEIPASS", ""), "tizorecover", "app", "web")

MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "bmp": "image/bmp", "webp": "image/webp", "ico": "image/x-icon", "svg": "image/svg+xml",
    "tif": "image/tiff", "tiff": "image/tiff", "avif": "image/avif",
    "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/mp4", "webm": "video/webm",
    "mkv": "video/x-matroska", "avi": "video/x-msvideo", "3gp": "video/mp4",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "opus": "audio/ogg",
    "flac": "audio/flac", "m4a": "audio/mp4", "aac": "audio/aac",
    "pdf": "application/pdf",
}
TEXT_EXTS = {"txt", "md", "csv", "log", "ini", "cfg", "json", "xml", "html", "htm", "yaml",
             "yml", "py", "js", "ts", "c", "h", "cpp", "cs", "java", "go", "rs", "php", "rb",
             "sh", "ps1", "bat", "css", "sql", "lua", "srt", "vtt", "toml", "rtf", "svg"}
OFFICE_TEXT = {"docx": "word/document.xml", "pptx": "ppt/slides/", "xlsx": "xl/sharedStrings.xml",
               "odt": "content.xml", "ods": "content.xml", "odp": "content.xml"}
CHANCES = {"good": "High", "partial": "Average", "overwritten": "Low"}
TEXT_LIMIT = 256 << 10
PREVIEW_SCAN = 48 << 20
THUMB_SCAN = 1 << 20            # RAW/HEIC: their small previews sit near the start
THUMB_SCAN_JPEG = 160 << 10     # a JPEG's EXIF thumbnail is inside its first 64 KB
THUMB_CACHE = 96 << 20


class _BytesSource:
    """A ``ByteSource`` over bytes already in memory."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.size = len(data)

    def at(self, offset: int, length: int) -> bytes:
        return self._data[offset:offset + length] if offset >= 0 else b""
OFFICE_LIMIT = 64 << 20


class App:
    """Everything the API needs between requests."""

    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.drives: list[drives_mod.Drive] = []
        self.images: list[drives_mod.Drive] = []
        self.drives_at = 0.0
        self.job: ScanJob | None = None
        self.recover: dict = {"state": "idle"}
        self.recover_stop = threading.Event()
        self.window = None
        self.planner = Planner()
        self.updater = Updater()
        self.erase: EraseJob | None = None
        self.lost: list[drives_mod.Drive] = []
        self.job_serial = 0
        self.parts: dict = {"state": "idle"}
        self.parts_stop = threading.Event()
        self.last_ping = time.time()
        self.lock = threading.Lock()
        self.diag: dict = {"state": "idle"}        # Fix Drive: the last diagnosis + its findings
        self.thumbs: dict = {}                     # (scan serial, item) -> small JPEG, newest last
        self.thumb_bytes = 0
        self.watch: fixdrive.Watch | None = None

    def all_drives(self, refresh: bool = False) -> list[drives_mod.Drive]:
        with self.lock:
            if refresh or not self.drives or time.time() - self.drives_at > 300:
                try:
                    self.drives = drives_mod.list_drives()
                except Exception:
                    self.drives = []
                self.drives_at = time.time()
            return self.drives + self.images + self.lost

    def find_drive(self, drive_id: str) -> drives_mod.Drive | None:
        return next((d for d in self.all_drives() if d.id == drive_id), None)

    def start_scan(self, drive: drives_mod.Drive, mode: str, resume: dict | None = None) -> None:
        if self.job is not None:
            self.job.close()
        mode = DEEP if mode == DEEP else QUICK
        self.job_serial += 1
        if resume is not None and resume.get("mode") == DEEP:
            mode = DEEP
        self.job = ScanJob(drive, mode, resume=resume, autosave=tzscan.auto_path(drive)).start()

    def search_partitions(self, target: str, thorough: bool) -> str | None:
        """Start a lost-partition search. Returns an error message, or None."""
        if self.parts.get("state") == "running":
            return "A partition search is already running."
        known = [d for d in self.all_drives() if not d.lost]
        if target.startswith("img:"):
            image = next((d for d in known if d.id == target), None)
            if image is None:
                return "Unknown disk image."
            sources = [(image.path, image.size, image, None)]
            label = image.label
        else:
            try:
                disk = int(target)
            except ValueError:
                return "Unknown disk."
            on_disk = [d for d in known if d.disk == disk and d.kind != "image"]
            if not on_disk:
                return "Unknown disk."
            label = on_disk[0].disk_name
            if drives_mod.is_admin() or sys.platform != "win32":
                path = f"\\\\.\\PhysicalDrive{disk}" if sys.platform == "win32" else on_disk[0].path
                sources = [(path, on_disk[0].disk_size, on_disk[0], on_disk)]
            else:
                vols = [d for d in on_disk if d.kind == "volume"]
                if not vols or not all(d.removable for d in vols):
                    return ("Searching a whole disk for lost partitions needs administrator rights. "
                            "Use Restart as administrator, then search again.")
                sources = [(d.path, d.size, d, None) for d in vols]
        self.lost = [d for d in self.lost if not d.id.startswith(f"lost:{target}:")]
        self.parts_stop.clear()
        state = {"state": "running", "target": target, "label": label, "thorough": thorough,
                 "done": 0, "total": sum(size for _p, size, _d, _l in sources), "found": 0, "error": ""}
        self.parts = state

        def progress(n: int) -> None:
            state["done"] += n

        def work() -> None:
            found_drives = []
            for path, _size, src_drive, live in sources:
                if self.parts_stop.is_set():
                    break
                try:
                    reader = open_source(path)
                except VolumeAccessError as exc:
                    state["error"] = str(exc)
                    continue
                try:
                    searcher = parts_mod.Searcher(reader)
                    run = searcher.thorough if thorough else searcher.quick
                    found = run(progress, self.parts_stop.is_set)
                    size = reader.size
                finally:
                    reader.close()
                if live is not None:
                    parts_mod.mark_current(found, [(d.disk_offset, d.size, d.filesystem) for d in live])
                else:
                    parts_mod.mark_current(found, [(0, src_drive.size, src_drive.filesystem)])
                    if src_drive.kind == "image":
                        for f in found:
                            f.current = f.current or f.start == 0
                for f in parts_mod.prune_overlaps([f for f in found if not f.current]):
                    found_drives.append(drives_mod.Drive(
                        id=f"lost:{target}:{path}:{f.start}:{f.filesystem}", kind="partition", path=path,
                        offset=f.start, size=max(0, min(f.size, size - f.start)), label=f.label,
                        letter="", filesystem=f.filesystem, free=0, disk=src_drive.disk,
                        disk_name=src_drive.disk_name, bus=src_drive.bus, media=src_drive.media,
                        removable=src_drive.removable, system=False, disk_size=src_drive.disk_size,
                        lost=True, found_by=f.found_by, boot_patch=f.boot_patch, patch_len=f.patch_len,
                        parent=target))
            self.lost = [d for d in self.lost if not d.id.startswith(f"lost:{target}:")] + found_drives
            state["found"] = len(found_drives)
            state["state"] = "stopped" if self.parts_stop.is_set() else ("failed" if state["error"] and not found_drives else "done")

        threading.Thread(target=work, name="tizo-parts", daemon=True).start()
        return None

    def remember_thumb(self, key, body: bytes) -> None:
        with self.lock:
            if key in self.thumbs:
                return
            self.thumbs[key] = body
            self.thumb_bytes += len(body)
            while self.thumb_bytes > THUMB_CACHE and self.thumbs:
                old = next(iter(self.thumbs))
                self.thumb_bytes -= len(self.thumbs.pop(old))

    def run_diagnose(self) -> None:
        if self.diag.get("state") == "running":
            return
        self.diag = {"state": "running", "started": time.time()}

        def work():
            try:
                data = fixdrive.diagnose()
                self.diag = {"state": "done", "data": data, "findings": fixdrive.findings(data), "at": time.time()}
            except Exception as exc:  # noqa: BLE001 - shown on the page
                crashlog.error("fix drive: diagnose", exc)
                self.diag = {"state": "failed", "error": f"Could not ask Windows about the drives: {exc}"}
        threading.Thread(target=work, name="tizo-diagnose", daemon=True).start()

    def eject(self, disk: int, force_scan: bool) -> str:
        """Eject a removable disk after letting go of our own handles to it."""
        drive = next((d for d in self.all_drives() if d.disk == disk and d.kind != "image" and not d.lost), None)
        if drive is None:
            raise EjectError("That drive is not there any more. It may already be unplugged.")
        if not drive.removable:
            raise EjectError("Only USB drives and memory cards can be ejected here.")
        if self.recover.get("state") == "running":
            dest_disk = drives_mod.disk_of_path(self.recover.get("dest", ""), self.all_drives())
            if dest_disk == disk or (self.job is not None and self.job.drive.disk == disk):
                raise EjectError("Files are being recovered from or to this drive. Wait until that is done.")
        if self.parts.get("state") == "running" and str(self.parts.get("target")) == str(disk):
            raise EjectError("A lost-partition search is running on this drive. Stop it first.")
        if self.erase is not None and getattr(self.erase, "state", "") == "running":
            raise EjectError("An erase is running. Wait until it is done.")
        if self.job is not None and self.job.drive.disk == disk and self.job.drive.kind != "image":
            if self.job.state in ("running", "starting") and not force_scan:
                raise EjectError("This drive is being scanned. Stop the scan first.")
            self.job.close()      # stops a running scan (progress is saved) and releases the drive
        if sys.platform == "win32":
            return eject_disk(disk)
        return eject_disk(f"/dev/{drive.disk_name}")

    def suggest_dest(self) -> str:
        """Where recovered files go by default: Desktop\\TizoRecover <date>, never on the scanned disk."""
        stamp = time.strftime("%Y-%m-%d")
        source = self.job.drive.disk if self.job is not None and self.job.drive.kind != "image" else None
        desktop = _desktop_dir()
        if desktop and drives_mod.disk_of_path(desktop, self.all_drives()) != source:
            return os.path.join(desktop, f"TizoRecover {stamp}")
        others = [d for d in self.all_drives() if d.letter and d.disk != source and d.kind == "volume" and d.free > 0]
        if others:
            best = max(others, key=lambda d: d.free)
            return f"{best.letter}:\\TizoRecover {stamp}"
        return ""

    def saved_scans(self) -> list[dict]:
        """Saved scans, each tied to a drive that is plugged in now (or ``drive_id`` None)."""
        by_key = {tzscan.drive_key(d): d for d in self.all_drives()}
        out = []
        for info in tzscan.list_saved():
            key = os.path.basename(info["path"])[:-len(tzscan.SUFFIX)]
            drive = by_key.get(key)
            info["drive_id"] = drive.id if drive is not None else None
            out.append(info)
        return out

    def pick(self, kind: str) -> str | None:
        """Native folder/file dialog: pywebview's when there is a window, else tkinter."""
        if self.window is not None:
            import webview
            if kind == "folder":
                got = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            else:
                got = self.window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=(("Saved scans (*.tzscan)",) if kind == "tzscan" else
                                ("Disk images (*.img;*.dd;*.raw;*.bin;*.iso;*.001)",))
                    + ("All files (*.*)",))
            if not got:
                return None
            return got[0] if isinstance(got, (list, tuple)) else got
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if kind == "folder":
                path = filedialog.askdirectory(parent=root)
            else:
                path = filedialog.askopenfilename(parent=root)
            root.destroy()
            return path or None
        except Exception:
            return None

    def run_recover(self, items, dest: str, keep_folders: bool) -> None:
        total = sum(it.candidate.size for it in items)
        self.recover_stop.clear()
        state = {"state": "running", "dest": dest, "files": len(items), "done_files": 0,
                 "bytes": total, "done_bytes": 0, "failed": [], "started": time.time()}
        self.recover = state

        def progress(n: int) -> None:
            state["done_bytes"] += n

        def work() -> None:
            done = 0
            failed = []
            for item in items:
                if self.recover_stop.is_set():
                    break
                result = save_items([item], self.job.data, dest, keep_folders, progress,
                                    self.recover_stop.is_set)
                for _it, path, ok, err in result:
                    done += 1
                    if not ok:
                        failed.append({"name": item.candidate.name or path, "error": err})
                state["done_files"] = done
                state["failed"] = failed
            report_path = _write_report(dest, self.job, items, failed)
            state["report"] = report_path
            state["state"] = "stopped" if self.recover_stop.is_set() else "done"

        threading.Thread(target=work, name="tizo-recover", daemon=True).start()


def _write_report(dest: str, job: ScanJob, items, failed) -> str:
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    path = os.path.join(dest, f"TizoRecover report {stamp}.txt")
    failed_names = {f["name"] for f in failed}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"{APP_NAME} {__version__} recovery report, {stamp}\n")
            fh.write(f"Drive: {job.drive.title} ({job.drive.path}), {job.filesystem}, "
                     f"{job.mode} scan\n")
            fh.write(f"Files: {len(items)}, failed: {len(failed)}\n\n")
            for it in items:
                c = it.candidate
                mark = "FAILED " if (c.name in failed_names) else ""
                chances = CHANCES.get(it.status, it.status)
                fh.write(f"{mark}[{chances} chances] {c.original_path or c.display_name}  "
                         f"({c.size:,} bytes, {c.strategy.value})\n")
    except OSError:
        return ""
    return path


def _space(dest: str, need: int, error: str) -> dict:
    """Free space where ``dest`` would land; an error when the files will not fit."""
    if not dest or not os.path.isabs(dest):
        return {}
    probe = dest
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return {}
    out = {"free": usage.free, "total": usage.total, "root": os.path.splitdrive(probe)[0] or probe}
    if not error and need > usage.free:
        out["error"] = (f"Not enough space there: the files need {need / 1e9:.1f} GB but only "
                        f"{usage.free / 1e9:.1f} GB is free.")
    return out


def _office_text(data: bytes, ext: str) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ""
    want = OFFICE_TEXT[ext]
    names = [n for n in zf.namelist() if n == want or (want.endswith("/") and n.startswith(want)
                                                       and n.endswith(".xml"))]
    out = []
    for name in sorted(names):
        try:
            xml = zf.read(name).decode("utf-8", "replace")
        except (KeyError, zipfile.BadZipFile, OSError, RuntimeError):
            continue
        xml = re.sub(r"</(w:p|a:p|text:p|si)>", "\n", xml)
        out.append(re.sub(r"<[^>]+>", "", xml))
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{__version__}"
    app: App = None  # set by make_server

    def log_message(self, fmt, *args) -> None:
        pass

    def _json(self, value, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _crashed(self, where: str, exc: Exception) -> None:
        crashlog.error(f"request {where}", exc)
        try:
            self._json({"error": f"Something went wrong ({type(exc).__name__}: {exc}). "
                                 f"It is written to the log.", "crash": True}, 500)
        except (OSError, ValueError):
            pass   # headers were already sent; the log has it

    def _authorised(self, query: dict) -> bool:
        token = self.headers.get("X-Tizo-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(token, self.app.token)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(min(length, 1 << 20)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not url.path.startswith("/api/"):
            return self._static(url.path)
        if not self._authorised(query):
            return self._error("forbidden", 403)
        self.app.last_ping = time.time()
        try:
            self._get(url.path, query)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except OSError as exc:   # the drive went away or a read failed: a message, not a crash report
            crashlog.log.warning("request %s: %s", url.path, exc)
            try:
                self._error("Could not read from the drive. If it was unplugged or ejected, plug it back in "
                            "and open its saved scan.", 409)
            except OSError:
                pass
        except Exception as exc:  # never a dead button: log it and tell the page
            self._crashed(url.path, exc)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not url.path.startswith("/api/") or not self._authorised(query):
            return self._error("forbidden", 403)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._error("json only", 415)
        self.app.last_ping = time.time()
        try:
            self._post(url.path, self._body())
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except OSError as exc:   # the drive went away or a read failed: a message, not a crash report
            crashlog.log.warning("request %s: %s", url.path, exc)
            try:
                self._error("Could not read from the drive. If it was unplugged or ejected, plug it back in "
                            "and open its saved scan.", 409)
            except OSError:
                pass
        except Exception as exc:  # never a dead button: log it and tell the page
            self._crashed(url.path, exc)

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(os.path.normpath(WEB)) or not os.path.isfile(full):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with open(full, "rb") as fh:
            body = fh.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
                         "frame-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _get(self, path: str, query: dict) -> None:
        app = self.app
        q = lambda k, d=None: (query.get(k) or [d])[0]
        if path == "/api/env":
            return self._json({"name": APP_NAME, "version": __version__,
                               "admin": drives_mod.is_admin(), "platform": sys.platform})
        if path == "/api/ping":
            return self._json({"ok": True})
        if path == "/api/fix":
            d = dict(app.diag)
            d.pop("data", None)
            return self._json(d)
        if path == "/api/fix/watch":
            return self._json(app.watch.status() if app.watch else {"state": "idle"})
        if path == "/api/suggest-dest":
            return self._json({"dest": app.suggest_dest()})
        if path == "/api/drive-mask":
            return self._json({"mask": _drive_mask()})
        if path == "/api/log":
            return self._json({"path": crashlog.path() or "", "text": crashlog.tail()})
        if path == "/api/drives":
            ds = app.all_drives(refresh=q("refresh") == "1")
            return self._json({"drives": [d.to_dict() for d in ds]})
        if path == "/api/scan":
            if app.job is None:
                return self._json({"state": "none"})
            return self._json({**app.job.status(), "job": app.job_serial})
        if path == "/api/items/changed":
            if app.job is None:
                return self._json({"items": [], "total": 0})
            items, total = app.job.changed_since(int(q("since", "0")))
            return self._json({"items": [it.to_dict() for it in items], "total": total})
        if path == "/api/items":
            if app.job is None:
                return self._json({"items": [], "total": 0})
            since = int(q("since", "0"))
            snap = app.job.snapshot()
            chunk = snap[since:since + 5000]
            return self._json({"items": [it.to_dict() for it in chunk], "total": len(snap)})
        if path == "/api/recover":
            return self._json(app.recover)
        if path == "/api/saved":
            return self._json({"saved": app.saved_scans(), "dir": tzscan.sessions_dir()})
        if path == "/api/partitions":
            return self._json(app.parts)
        if path == "/api/update":
            return self._json(app.updater.check())
        if path == "/api/update/status":
            return self._json(app.updater.state)
        if path == "/api/erase":
            return self._json(app.erase.status() if app.erase else {"state": "idle"})
        m = re.fullmatch(r"/api/item/(\d+)(?:/(data|hex|text|preview|thumb))?", path)
        if m:
            if app.job is None:
                return self._error("no scan", 404)
            item = app.job.item(int(m.group(1)))
            if item is None:
                return self._error("no such file", 404)
            what = m.group(2)
            if what is None:
                return self._json(item.details())
            if what == "data":
                return self._data(item, q("download") == "1")
            if what == "preview":
                return self._preview(item)
            if what == "thumb":
                return self._thumb(item)
            if what == "hex":
                return self._hex(item, int(q("offset", "0")), min(int(q("length", "4096")), 65536))
            return self._text(item)
        return self._error("not found", 404)

    def _post(self, path: str, body: dict) -> None:
        app = self.app
        if path == "/api/fix/check":
            app.run_diagnose()
            return self._json({"ok": True})
        if path == "/api/fix/apply":
            data = (app.diag or {}).get("data")
            if not data:
                return self._error("Check the drives first.")
            wanted = str(body.get("id", ""))
            finding = next((f for f in app.diag.get("findings", []) if f["id"] == wanted and f.get("fix")), None)
            if finding is None:
                return self._error("That problem is gone. Check again.")
            try:
                message = fixdrive.apply(finding["fix"], data)
            except fixdrive.FixError as exc:
                return self._error(str(exc))
            crashlog.log.info("fix drive: %s -> %s", finding["fix"].get("action"), message)
            app.run_diagnose()
            return self._json({"ok": True, "message": message})
        if path == "/api/fix/watch":
            if body.get("stop"):
                if app.watch:
                    app.watch.stop()
                return self._json({"ok": True})
            if app.watch and app.watch.state == "watching":
                return self._error("Already watching.")
            app.watch = fixdrive.Watch(int(body.get("seconds", 45))).start()
            return self._json({"ok": True})
        if path == "/api/eject":
            try:
                message = app.eject(int(body.get("disk", -1)), bool(body.get("force_scan")))
            except (EjectError, ValueError) as exc:
                return self._error(str(exc))
            with app.lock:
                app.drives_at = 0.0
            return self._json({"ok": True, "message": message})
        if path == "/api/quit":
            self._json({"ok": True})
            if app.job is not None:
                app.job.stop()
            if app.window is not None:
                threading.Timer(0.2, app.window.destroy).start()
            else:
                threading.Timer(0.5, lambda: os._exit(0)).start()
            return None
        if path == "/api/client-error":
            crashlog.log.error("page: %s", str(body.get("message", ""))[:4000])
            return self._json({"ok": True})
        if path == "/api/scan":
            drive = app.find_drive(str(body.get("drive", "")))
            if drive is None:
                return self._error("unknown drive")
            resume = None
            if body.get("resume"):
                try:
                    resume = tzscan.load(tzscan.auto_path(drive))
                except (OSError, ValueError, EOFError) as exc:
                    return self._error(f"Could not open the saved scan: {exc}")
            app.start_scan(drive, str(body.get("mode", QUICK)), resume)
            return self._json({"ok": True})
        if path == "/api/scan/open":
            try:
                saved = tzscan.load(str(body.get("path", "")))
            except (OSError, ValueError, EOFError) as exc:
                return self._error(f"That is not a scan TizoRecover can open: {exc}")
            want = saved.get("drive") or {}
            drive = next((d for d in app.all_drives(refresh=True)
                          if d.id == want.get("id") and d.size == want.get("size")), None)
            if drive is None:
                name = want.get("letter") and f"{want.get('letter')}: " or ""
                return self._error(f"Plug in the drive this scan came from ({name}{want.get('label') or want.get('disk_name') or 'unknown'}, "
                                   f"{(want.get('size') or 0) / 1e9:.1f} GB), then open it again.")
            app.start_scan(drive, saved.get("mode", QUICK), saved)
            return self._json({"ok": True, "drive": drive.to_dict()})
        if path == "/api/partitions/search":
            problem = app.search_partitions(str(body.get("target", "")), bool(body.get("thorough")))
            if problem:
                return self._error(problem)
            return self._json({"ok": True})
        if path == "/api/partitions/stop":
            app.parts_stop.set()
            return self._json({"ok": True})
        if path == "/api/saved/delete":
            target = os.path.abspath(str(body.get("path", "")))
            if os.path.dirname(target) == os.path.abspath(tzscan.sessions_dir()) and target.endswith(tzscan.SUFFIX):
                for p in (target, target + ".info"):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            return self._json({"ok": True})
        if path == "/api/scan/pause":
            if app.job is not None:
                app.job.resume_scan() if body.get("resume") else app.job.pause()
            return self._json({"ok": True})
        if path == "/api/scan/stop":
            if app.job is not None:
                app.job.stop()
            return self._json({"ok": True})
        if path == "/api/pick":
            return self._json({"path": app.pick(str(body.get("kind", "folder")))})
        if path == "/api/image":
            p = str(body.get("path", ""))
            if not os.path.isfile(p):
                return self._error("not a file")
            drive = drives_mod.image_drive(p)
            app.images = [d for d in app.images if d.id != drive.id] + [drive]
            return self._json({"drive": drive.to_dict()})
        if path == "/api/check-dest":
            dest = str(body.get("dest", ""))
            result = self._dest_problem(dest)
            result.update(_space(dest, int(body.get("need") or 0), result["error"]))
            return self._json(result)
        if path == "/api/recover":
            if app.job is None:
                return self._error("no scan")
            if app.recover.get("state") == "running":
                return self._error("a recovery is already running")
            dest = str(body.get("dest", ""))
            problem = self._dest_problem(dest)
            if problem["error"]:
                return self._error(problem["error"])
            ids = body.get("ids") or []
            items = [it for it in (app.job.item(int(i)) for i in ids) if it is not None]
            if not items:
                return self._error("nothing selected")
            space = _space(dest, sum(it.candidate.size for it in items), "")
            if space.get("error"):
                return self._error(space["error"])
            app.run_recover(items, dest, bool(body.get("keep_folders", True)))
            return self._json({"ok": True})
        if path == "/api/recover/stop":
            app.recover_stop.set()
            return self._json({"ok": True})
        if path == "/api/open-folder":
            target = str(body.get("path", ""))
            if os.path.exists(target) and sys.platform == "win32":
                if os.path.isfile(target):
                    subprocess.Popen(["explorer", "/select,", target])
                else:
                    os.startfile(target)
            return self._json({"ok": True})
        if path == "/api/erase/prepare":
            try:
                return self._json(app.planner.prepare(int(body.get("disk", -1))))
            except (EraseError, ValueError) as exc:
                return self._error(str(exc))
        if path == "/api/erase/start":
            if app.erase is not None and app.erase.state == "running":
                return self._error("An erase is already running.")
            if app.recover.get("state") == "running":
                return self._error("Wait for the recovery to finish first.")
            try:
                plan = app.planner.confirm(str(body.get("token", "")), str(body.get("typed", "")),
                                           body.get("understood") is True)
            except EraseError as exc:
                return self._error(str(exc))
            if app.job is not None and app.job.drive.disk == plan.disk:
                app.job.close()
                app.job = None
            app.erase = EraseJob(plan, str(body.get("method", "quick")),
                                 body.get("filesystem") or None, str(body.get("label", "USB"))).start()
            app.drives_at = 0
            return self._json({"ok": True})
        if path == "/api/erase/stop":
            if app.erase is not None:
                app.erase.stop()
            return self._json({"ok": True})
        if path == "/api/update/install":
            return self._json(app.updater.install())
        if path == "/api/open-url":
            url = str(body.get("url", ""))
            if url.startswith("https://github.com/BKHornYT/TizoRecover"):
                import webbrowser
                webbrowser.open(url)
            return self._json({"ok": True})
        if path == "/api/elevate":
            return self._json({"ok": relaunch_as_admin()})
        return self._error("not found", 404)

    def _dest_problem(self, dest: str) -> dict:
        app = self.app
        if not dest:
            return {"error": "Choose a folder to save to."}
        if not os.path.isabs(dest):
            return {"error": "Choose a full folder path."}
        job = app.job
        if job is None:
            return {"error": "No scan to recover from."}
        drive = job.drive
        if drive.kind == "image":
            return {"error": ""}
        disk = drives_mod.disk_of_path(dest, app.all_drives())
        if disk is not None and disk == drive.disk:
            return {"error": "That folder is on the drive you are recovering from. Saving there "
                             "can overwrite the very files you want back. Pick a folder on "
                             "another drive."}
        return {"error": ""}

    def _data(self, item, download: bool) -> None:
        data = self.app.job.data(item)
        size = data.size
        ext = item.candidate.ext.lower()
        ctype = MIME.get(ext, "text/plain; charset=utf-8" if ext in TEXT_EXTS
                         else "application/octet-stream")
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        # Item URLs carry the scan number (?g=), so a cached copy can never be
        # another scan's file; caching keeps thumbnails from reloading on scroll.
        self.send_header("Cache-Control", "private, max-age=900")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            name = re.sub(r'[^\w.\- ]', "_", item.candidate.name or "file")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        for block in data.chunks(1 << 20, start, end + 1):
            self.wfile.write(block)

    @staticmethod
    def _embedded_jpegs(blob: bytes, min_size: int = 2048) -> list[tuple[int, int]]:
        """Every intact JPEG inside ``blob``, as (offset, size)."""
        found = []
        view = _BytesSource(blob)
        pos = blob.find(b"\xff\xd8\xff")
        tries = 0
        while pos >= 0 and tries < 64:
            tries += 1
            extent = formats_mod._jpeg_walk(view, pos, len(blob))
            if extent is not None and extent.verdict.value == "valid" and extent.size > min_size:
                found.append((pos, extent.size))
                if pos > 0:
                    pos = blob.find(b"\xff\xd8\xff", pos + extent.size)
                    continue
            pos = blob.find(b"\xff\xd8\xff", pos + 3)
        return found

    def _send_jpeg(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=900")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _preview(self, item) -> None:
        """The largest intact JPEG inside a file the window cannot show itself.

        Camera RAW files (CR2, NEF, ARW, DNG, ...) carry a full-size JPEG
        preview, MP3s their album art, many videos and TIFFs a thumbnail.
        """
        data = self.app.job.data(item)
        blob = data.at(0, min(data.size, PREVIEW_SCAN))
        found = self._embedded_jpegs(blob)
        best = max(found, key=lambda f: f[1]) if found else None
        if best is None or (best[0] == 0 and item.candidate.ext.lower() in ("jpg", "jpeg")):
            return self._error("no embedded preview", 404)
        self._send_jpeg(blob[best[0]:best[0] + best[1]])

    def _thumb(self, item) -> None:
        """A small picture for the gallery and the grid, cheap to read from a slow drive.

        Cameras store a ~160 px thumbnail in a photo's EXIF block (and RAW/HEIC files carry
        several previews): that is a few KB from the start of the file instead of the whole
        5-25 MB picture. Without one, the full image is sent (the browser scales it).
        Kept in memory, so scrolling back is instant.
        """
        app = self.app
        key = (app.job_serial, item.id)
        cached = app.thumbs.get(key)
        if cached is not None:
            return self._send_jpeg(cached)
        data = app.job.data(item)
        ext = item.candidate.ext.lower()
        head = data.at(0, min(data.size, THUMB_SCAN_JPEG if ext in ("jpg", "jpeg") else THUMB_SCAN))
        inner = [f for f in self._embedded_jpegs(head, 1024) if f[0] > 0]
        if inner:
            pos, size = min(inner, key=lambda f: f[1]) if ext in ("jpg", "jpeg") else \
                min((f for f in inner if f[1] >= 8192), key=lambda f: f[1], default=min(inner, key=lambda f: f[1]))
            body = head[pos:pos + size]
            app.remember_thumb(key, body)
            return self._send_jpeg(body)
        if ext in ("jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "svg", "avif") and data.size <= 40_000_000:
            return self._data(item, False)
        return self._preview(item)

    def _hex(self, item, offset: int, length: int) -> None:
        data = self.app.job.data(item)
        blob = data.at(max(0, offset), length)
        rows = []
        for i in range(0, len(blob), 16):
            row = blob[i:i + 16]
            rows.append([offset + i, row.hex(" "),
                         "".join(chr(b) if 32 <= b < 127 else "." for b in row)])
        return self._json({"offset": offset, "size": data.size, "rows": rows})

    def _text(self, item) -> None:
        data = self.app.job.data(item)
        ext = item.candidate.ext.lower()
        if ext in OFFICE_TEXT:
            if data.size > OFFICE_LIMIT:
                return self._json({"text": "", "note": "too large to extract text from"})
            text = _office_text(data.read_all(), ext)
            return self._json({"text": text[:TEXT_LIMIT], "truncated": len(text) > TEXT_LIMIT})
        blob = data.at(0, TEXT_LIMIT)
        for enc in ("utf-8", "utf-16"):
            try:
                text = blob.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = blob.decode("cp1252", "replace")
        return self._json({"text": text, "truncated": data.size > TEXT_LIMIT})


def relaunch_as_admin() -> bool:
    """Start this program again elevated (UAC prompt); the caller then exits."""
    if sys.platform != "win32":
        return False
    import ctypes
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, ""
    else:
        exe, args = sys.executable, "-m tizorecover"
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, os.getcwd(), 1)
    if rc > 32:
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return True
    return False


def _desktop_dir() -> str:
    """The real Desktop folder (OneDrive moves it), "" when there is none."""
    if sys.platform == "win32":
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and os.path.isdir(buf.value):
            return buf.value
    path = os.path.join(os.path.expanduser("~"), "Desktop")
    return path if os.path.isdir(path) else ""


def _drive_mask() -> int:
    """Which drive letters exist: cheap enough to poll, so a plugged-in stick shows up by itself."""
    if sys.platform == "win32":
        import ctypes
        return int(ctypes.windll.kernel32.GetLogicalDrives())
    try:
        return hash(tuple(sorted(os.listdir("/sys/block"))))
    except OSError:
        return 0


def make_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    handler = type("TizoHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
