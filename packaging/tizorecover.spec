# PyInstaller spec for TizoRecover.
#
# Build on Windows from the repository root with:
#     powershell -File packaging\build.ps1
#
# Two exes come out of one analysis:
#   dist\TizoRecover.exe      the window, no console behind it
#   dist\TizoRecover-cli.exe  the command line (tizorecover drives / scan E:)
#
# Neither asks for administrator rights up front: USB sticks and memory cards
# can be read without them, and the window offers to restart elevated when an
# internal drive needs it.

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "tizorecover.ico")
VERSION = os.path.join(SPECPATH, "version_info.txt")

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

common = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION,
)

gui = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="TizoRecover", console=False, **common)
cli = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="TizoRecover-cli", console=True, **common)
