# PyInstaller spec: the folder build (dist/TizoRecover/) with both programs.
#
# This folder is what the installer installs, what the -x64.zip contains and, on Linux, what goes
# into the AppImage. Two programs share one set of libraries:
#   TizoRecover(.exe)      the window, no console behind it (Windows)
#   TizoRecover-cli(.exe)  the command line (tizorecover drives / scan E:)
# Neither asks for administrator rights up front: removable drives read without them, and the
# window offers to restart elevated for internal drives.
#
#   python -m PyInstaller --noconfirm --clean packaging/tizorecover.spec

import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
WINDOWS = sys.platform == "win32"
ICON = os.path.join(SPECPATH, "tizorecover.ico") if WINDOWS else None
VERSION = os.path.join(SPECPATH, "version_info.txt") if WINDOWS else None

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "tizorecover", "app", "web"), os.path.join("tizorecover", "app", "web"))],
    hiddenimports=["webview", "webview.platforms.edgechromium", "webview.platforms.winforms"] if WINDOWS else [],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # On Linux the window opens in the browser (no GTK/WebKit to bundle), so pywebview stays out.
    excludes=["pytest", "numpy", "PIL", "playwright", "setuptools", "pip", "unittest", "test", "tkinter.test"]
             + ([] if WINDOWS else ["webview"]),
    noarchive=False,
)

pyz = PYZ(a.pure)

common = dict(exclude_binaries=True, debug=False, bootloader_ignore_signals=False, strip=False,
              upx=False, icon=ICON, version=VERSION)

gui = EXE(pyz, a.scripts, [], name="TizoRecover", console=not WINDOWS, **common)
cli = EXE(pyz, a.scripts, [], name="TizoRecover-cli", console=True, **common)

COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="TizoRecover")
