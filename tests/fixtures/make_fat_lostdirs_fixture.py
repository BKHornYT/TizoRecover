"""Rebuilds ``fat-lostdirs.img.gz``: a real FAT32 volume (dosfstools + mtools, Linux) quick-formatted over.

Photos in ``DCIM/100MEDIA``, documents with no signature in ``Documents/Work`` and music in ``Music``;
then ``mkfs.vfat`` writes a new FAT and an empty root folder on top and one new file is copied in. The
old folders' clusters are still in the data area with all their entries: what ``fat.LooseDirs`` finds.

Needs WSL ``Ubuntu-24.04`` with root, ``dosfstools`` and ``mtools``.

    python tests/fixtures/make_fat_lostdirs_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from tests.test_session import noisy_png  # noqa: E402


def sources() -> dict[str, bytes]:
    rng = random.Random(21)
    files = {f"DCIM/100MEDIA/IMG_{3000 + i}.png": noisy_png(40 + i * 2, 30 + i, 300 + i) for i in range(40)}
    for i in range(15):
        files[f"Documents/Work/Quarterly report {i:02d}.dat"] = rng.randbytes(5000 + i * 1700)
    for i in range(5):
        files[f"Music/Track {i + 1}.dat"] = rng.randbytes(60_000 + i * 9000)
    return files


def main() -> None:
    files = sources()
    work = tempfile.mkdtemp(prefix="tizo-fatlost-")
    for name, data in files.items():
        path = os.path.join(work, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    out = os.path.join(HERE, "fat-lostdirs.img.gz")
    script = os.path.join(HERE, "make_fat_lostdirs_fixture.sh")
    to_wsl = lambda p: subprocess.run(["wsl", "-d", "Ubuntu-24.04", "wslpath", p.replace(os.sep, "/")],  # noqa: E731
                                      capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "bash", to_wsl(script), to_wsl(work), to_wsl(out)],
                   check=True, env=env)
    manifest = {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}
    with open(os.path.join(HERE, "fat-lostdirs.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("fixture written:", out)


if __name__ == "__main__":
    main()
