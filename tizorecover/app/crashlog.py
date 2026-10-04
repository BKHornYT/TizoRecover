"""One log file for everything that goes wrong, so nothing fails silently.

The windowed exe has no console: an uncaught error in a thread, a request
handler or the page itself would otherwise vanish, and the user only sees a
button that does nothing. Everything lands in ``logs/tizorecover.log`` next to
the saved scans (kept small: 1 MB, 3 old copies), and the page can show the
last lines in its "Something went wrong" panel so a report is one copy away.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback

from tizorecover import __version__

log = logging.getLogger("tizorecover")
_path: str | None = None


def logs_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    path = os.path.join(base, "TizoRecover", "logs")
    os.makedirs(path, exist_ok=True)
    return path


def setup() -> str | None:
    """Start logging to the file and catch every uncaught error. Safe to call twice."""
    global _path
    if _path:
        return _path
    try:
        path = os.path.join(logs_dir(), "tizorecover.log")
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1 << 20, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    _path = path
    log.info("start %s %s on %s, python %s", "TizoRecover", __version__, platform.platform(), sys.version.split()[0])

    def main_hook(kind, value, tb):
        log.critical("uncaught: %s", "".join(traceback.format_exception(kind, value, tb)))
        if sys.__excepthook__ and sys.stderr:
            sys.__excepthook__(kind, value, tb)

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        log.error("uncaught in thread %s: %s", getattr(args.thread, "name", "?"),
                  "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = main_hook
    threading.excepthook = thread_hook
    return path


def error(where: str, exc: BaseException) -> None:
    log.error("%s: %s", where, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def tail(lines: int = 60) -> str:
    """The end of the log, for the error panel's "copy report"."""
    if not _path:
        return ""
    try:
        with open(_path, encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


def path() -> str | None:
    return _path
