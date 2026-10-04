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
from tizorecover.engine import tzscan
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tizorecover.engine.writer import save_items
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
        self.last_ping = time.time()
        self.lock = threading.Lock()

    def all_drives(self, refresh: bool = False) -> list[drives_mod.Drive]:
        with self.lock:
            if refresh or not self.drives or time.time() - self.drives_at > 300:
                try:
                    self.drives = drives_mod.list_drives()
                except Exception:
                    self.drives = []
                self.drives_at = time.time()
            return self.drives + self.images

    def find_drive(self, drive_id: str) -> drives_mod.Drive | None:
        return next((d for d in self.all_drives() if d.id == drive_id), None)

    def start_scan(self, drive: drives_mod.Drive, mode: str, resume: dict | None = None) -> None:
        if self.job is not None:
            self.job.close()
        mode = DEEP if mode == DEEP else QUICK
        if resume is not None and resume.get("mode") == DEEP:
            mode = DEEP
        self.job = ScanJob(drive, mode, resume=resume, autosave=tzscan.auto_path(drive)).start()

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
        if path == "/api/drives":
            ds = app.all_drives(refresh=q("refresh") == "1")
            return self._json({"drives": [d.to_dict() for d in ds]})
        if path == "/api/scan":
            if app.job is None:
                return self._json({"state": "none"})
            return self._json(app.job.status())
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
            return self._json({"saved": app.saved_scans()})
        if path == "/api/update":
            return self._json(app.updater.check())
        if path == "/api/update/status":
            return self._json(app.updater.state)
        if path == "/api/erase":
            return self._json(app.erase.status() if app.erase else {"state": "idle"})
        m = re.fullmatch(r"/api/item/(\d+)(?:/(data|hex|text))?", path)
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
            if what == "hex":
                return self._hex(item, int(q("offset", "0")), min(int(q("length", "4096")), 65536))
            return self._text(item)
        return self._error("not found", 404)

    def _post(self, path: str, body: dict) -> None:
        app = self.app
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
        if path == "/api/saved/delete":
            target = os.path.abspath(str(body.get("path", "")))
            if os.path.dirname(target) == os.path.abspath(tzscan.sessions_dir()) and target.endswith(tzscan.SUFFIX):
                for p in (target, target + ".info"):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            name = re.sub(r'[^\w.\- ]', "_", item.candidate.name or "file")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        for block in data.chunks(1 << 20, start, end + 1):
            self.wfile.write(block)

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


def make_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    handler = type("TizoHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
