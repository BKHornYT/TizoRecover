"""Rebuilds ``ext4-deleted.img.gz``: a real ext4 volume made and changed by Linux.

Needs WSL (or Linux) with root, mkfs.ext4 and loop mounts. The source files
are deterministic, so their checksums (``ext4-deleted.json``) never change;
the image itself differs per run (times, journal), which the test allows.

    python tests/fixtures/make_ext4_fixture.py
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

from tests import samples  # noqa: E402
from tests.test_session import noisy_png  # noqa: E402


def sources() -> dict[str, bytes]:
    rng = random.Random(77)
    files = {
        "photo1.png": noisy_png(150, 110, 1), "photo2.png": noisy_png(120, 90, 2),
        "report.pdf": samples.make_pdf(3), "notes.txt": b"ext4 notes\n" * 400,
        "plan.txt": b"plan inside a deleted folder\n" * 500, "data.bin": rng.randbytes(70_000),
    }
    for i in range(1, 7):
        files[f"frag_part{i}"] = rng.randbytes(20_000)
        files[f"filler_part{i}"] = rng.randbytes(20_000)
    return files


def expected(files: dict[str, bytes]) -> dict[str, str]:
    frag = b"".join(files[f"frag_part{i}"] for i in range(1, 7))
    want = {
        "home/user/Photos/photo1.png": files["photo1.png"], "home/user/report.pdf": files["report.pdf"],
        "home/user/frag.bin": frag, "home/user/Old/plan.txt": files["plan.txt"],
        "home/user/Old/data.bin": files["data.bin"],
    }
    return {k: hashlib.sha256(v).hexdigest() for k, v in want.items()}


def main() -> None:
    files = sources()
    work = tempfile.mkdtemp(prefix="tizo-ext4fix-")
    for name, data in files.items():
        with open(os.path.join(work, name), "wb") as fh:
            fh.write(data)
    out = os.path.join(HERE, "ext4-deleted.img.gz")
    script = os.path.join(HERE, "make_ext4_fixture.sh")
    to_wsl = lambda p: subprocess.run(["wsl", "-d", "Ubuntu-24.04", "wslpath", p.replace(os.sep, "/")],  # noqa: E731
                                      capture_output=True,
                                      text=True, check=True).stdout.strip()
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "bash", to_wsl(script), to_wsl(work), to_wsl(out)],
                   check=True, env=env)
    with open(os.path.join(HERE, "ext4-deleted.json"), "w") as fh:
        json.dump(expected(files), fh, indent=1)
    print("fixture written:", out)


if __name__ == "__main__":
    main()
