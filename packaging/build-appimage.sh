#!/usr/bin/env bash
# Build release/TizoRecover-<v>-x86_64.AppImage (+ latest-linux.yml) on Linux. Run from the repo root.
# The window opens in the browser on Linux (pywebview is left out: no GTK/WebKit to bundle), and
# reading a raw device needs root:  sudo ./TizoRecover-<v>-x86_64.AppImage scan /dev/sdb1
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tests/run_all.py
V=$(python3 packaging/release_tools.py version)
python3 -m pip install --quiet pyinstaller
rm -rf dist build AppDir
python3 -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/tizorecover.spec

mkdir -p AppDir/usr/lib release
cp -r dist/TizoRecover AppDir/usr/lib/tizorecover
cp packaging/tizorecover.png AppDir/tizorecover.png
cat > AppDir/tizorecover.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=TizoRecover
Comment=Find and recover deleted files
Exec=TizoRecover
Icon=tizorecover
Categories=Utility;System;
Terminal=false
DESKTOP
cat > AppDir/AppRun <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/tizorecover/TizoRecover" "$@"
RUN
chmod +x AppDir/AppRun

TOOL=build/appimagetool
[ -x "$TOOL" ] || { curl -fsSL -o "$TOOL" \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; chmod +x "$TOOL"; }
OUT="release/TizoRecover-$V-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream AppDir "$OUT"
python3 packaging/release_tools.py feed "$OUT" release/latest-linux.yml

# smoke test: the AppImage starts and recovers from a synthetic disk image
APPIMAGE_EXTRACT_AND_RUN=1 "$OUT" --version
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from tests import fsimages, samples
b = fsimages.Fat32Builder(); b.add_deleted_file("smoke.pdf", samples.make_pdf(2), free_chain=True)
open("build/smoke.img", "wb").write(b.build())
PY
APPIMAGE_EXTRACT_AND_RUN=1 "$OUT" scan build/smoke.img --list | tee build/smoke.txt
grep -q "smoke.pdf" build/smoke.txt
ls -la release
