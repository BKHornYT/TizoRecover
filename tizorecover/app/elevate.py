"""The window always runs with administrator (root) rights.

Deleted files only exist in a drive's raw bytes, and reading those needs an
elevated process for anything but some USB sticks; half-working without it
confused people, so the window never runs without it (owner, 2026-10-05).

The released Windows exe carries a ``requireAdministrator`` manifest, so
Windows asks before the program even starts; this module is the same rule for
everything else: ``python -m tizorecover``, the zip, and Linux (``pkexec``).
``TIZORECOVER_NO_ELEVATE=1`` skips it for development and tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from tizorecover import APP_NAME
from tizorecover.engine.drives import is_admin

SKIP_ENV = "TIZORECOVER_NO_ELEVATE"
NEEDS_TEXT = (f"{APP_NAME} needs administrator rights to read deleted files from a drive.\n\n"
              f"Start it again and choose Yes when Windows asks.")
# Variables a graphical program needs that pkexec throws away.
_LINUX_KEEP = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
               "APPIMAGE", "APPDIR", "LANG")


def _self_command() -> tuple[str, list[str]]:
    """The program and arguments that start this same window again."""
    args = sys.argv[1:]
    if os.environ.get("APPIMAGE"):
        return os.environ["APPIMAGE"], args
    if getattr(sys, "frozen", False):
        return sys.executable, args
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        quiet = exe[:-len("python.exe")] + "pythonw.exe"   # no console window behind the elevated copy
        if os.path.isfile(quiet):
            exe = quiet
    return exe, ["-m", "tizorecover", *args]


def _message(text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x30)   # MB_ICONWARNING
            return
        except (AttributeError, OSError):
            pass
    print(text, file=sys.stderr)


def _windows_relaunch() -> bool:
    import ctypes
    exe, args = _self_command()
    params = subprocess.list2cmdline(args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.getcwd(), 1)
    return rc > 32


def _linux_relaunch() -> bool:
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False
    exe, args = _self_command()
    keep = [f"{k}={os.environ[k]}" for k in _LINUX_KEEP if os.environ.get(k)]
    try:
        return subprocess.run([pkexec, "env", *keep, exe, *args]).returncode == 0
    except OSError:
        return False


def ensure_admin() -> bool:
    """True: carry on in this process. False: exit (an elevated copy took over, or the user said no)."""
    if is_admin() or os.environ.get(SKIP_ENV) == "1":
        return True
    if sys.platform == "win32":
        if not _windows_relaunch():
            _message(NEEDS_TEXT)
        return False
    if sys.platform.startswith("linux"):
        # pkexec runs the elevated copy in the foreground, so this process just waits for it.
        if not _linux_relaunch() and not shutil.which("pkexec"):
            _message(f"{APP_NAME} needs root to read deleted files. Run it with sudo.")
        return False
    return True


def original_user() -> str | None:
    """Who started us before pkexec/sudo made us root (to open their browser, not root's)."""
    uid = os.environ.get("PKEXEC_UID")
    if uid:
        try:
            import pwd
            return pwd.getpwuid(int(uid)).pw_name
        except (ImportError, KeyError, ValueError):
            return None
    return os.environ.get("SUDO_USER")
