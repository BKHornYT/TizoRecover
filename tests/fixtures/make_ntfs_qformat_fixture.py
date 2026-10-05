"""Rebuilds ``ntfs-qformat.img.gz``: a real NTFS volume (ntfs-3g, Linux) that was quick-formatted.

Photos in ``DCIM/Camera``, documents in ``Documents/Work`` (random bytes with no file signature:
only a file record can bring those back) and a video. (ntfs-3g keeps the video in one piece
whatever we try; test_qformat plants a fragmented record itself.)
Then ``mkntfs -Q`` puts a new, empty NTFS on top and one small file is written. The new $MFT
overwrites only the start of the old one; the rest of the old records lie in free space.
The deep scan's old-record search (``ntfs.LooseRecords``) is what this fixture is for.

Needs WSL ``Ubuntu-24.04`` with root and ``ntfs-3g`` (``apt install ntfs-3g``).

    python tests/fixtures/make_ntfs_qformat_fixture.py
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
    rng = random.Random(11)
    files = {f"DCIM/Camera/IMG_{2000 + i}.png": noisy_png(50 + i * 2, 40 + i, 100 + i) for i in range(60)}
    for i in range(20):
        files[f"Documents/Work/report_{i:02d}.dat"] = rng.randbytes(9000 + i * 1500)
    files["Videos/holiday.mov"] = rng.randbytes(700_000)
    return files


def main() -> None:
    files = sources()
    work = tempfile.mkdtemp(prefix="tizo-qformat-")
    for name, data in files.items():
        path = os.path.join(work, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    out = os.path.join(HERE, "ntfs-qformat.img.gz")
    script = os.path.join(HERE, "make_ntfs_qformat_fixture.sh")
    to_wsl = lambda p: subprocess.run(["wsl", "-d", "Ubuntu-24.04", "wslpath", p.replace(os.sep, "/")],  # noqa: E731
                                      capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "bash", to_wsl(script), to_wsl(work), to_wsl(out)],
                   check=True, env=env)
    manifest = {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}
    with open(os.path.join(HERE, "ntfs-qformat.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("fixture written:", out)


if __name__ == "__main__":
    main()
