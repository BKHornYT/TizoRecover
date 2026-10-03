# PyInstaller spec: the single-file portable window (Windows), released as TizoRecover-<ver>-portable.exe.
# Runs from anywhere, including another USB stick, without installing anything.
#
#   python -m PyInstaller --noconfirm --clean packaging/portable.spec

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "tizorecover", "app", "web"), os.path.join("tizorecover", "app", "web"))],
    hiddenimports=["webview", "webview.platforms.edgechromium", "webview.platforms.winforms"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "numpy", "PIL", "playwright", "setuptools", "pip", "unittest", "test", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

EXE(pyz, a.scripts, a.binaries, a.datas, [], name="TizoRecover-portable", console=False,
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, runtime_tmpdir=None,
    icon=os.path.join(SPECPATH, "tizorecover.ico"), version=os.path.join(SPECPATH, "version_info.txt"))
