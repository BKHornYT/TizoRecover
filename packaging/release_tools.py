"""Release helpers, used by packaging/build.ps1 and the release workflow.

    python packaging/release_tools.py version           print the app version
    python packaging/release_tools.py check-tag v0.1.1  fail unless the tag matches the version
    python packaging/release_tools.py version-info      write packaging/version_info.txt
    python packaging/release_tools.py feed <file> <out> write an electron-builder style update feed

The feed (latest.yml / latest-linux.yml) has the same shape electron-builder writes for the other
Tizo apps, so every Tizo release looks alike and the in-app updater reads it.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version() -> str:
    text = open(os.path.join(ROOT, "tizorecover", "__init__.py"), encoding="utf-8").read()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def version_info() -> None:
    v = version()
    nums = (tuple(int(x) for x in re.findall(r"\d+", v)) + (0, 0, 0, 0))[:4]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'TizoRecover contributors'),
      StringStruct('FileDescription', 'TizoRecover - free, open-source file recovery'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'TizoRecover'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'TizoRecover.exe'),
      StringStruct('ProductName', 'TizoRecover'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(os.path.join(ROOT, "packaging", "version_info.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)


def feed(path: str, out: str) -> None:
    digest = hashlib.sha512()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    sha = base64.b64encode(digest.digest()).decode()
    name = os.path.basename(path)
    size = os.path.getsize(path)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"version: {version()}\nfiles:\n  - url: {name}\n    sha512: {sha}\n    size: {size}\n"
                 f"path: {name}\nsha512: {sha}\nreleaseDate: '{stamp}'\n")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "version":
        print(version())
    elif cmd == "check-tag":
        tag = argv[1].removeprefix("refs/tags/").removeprefix("v")
        if tag != version():
            print(f"tag v{tag} does not match tizorecover.__version__ {version()}")
            return 1
        print(f"releasing {version()}")
    elif cmd == "version-info":
        version_info()
    elif cmd == "feed":
        feed(argv[1], argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
