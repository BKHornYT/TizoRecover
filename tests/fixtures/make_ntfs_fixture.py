"""Rebuilds ``ntfs-i30.img.gz``: a real NTFS volume made and changed by ntfs-3g (Linux).

40 PNG photos (all different sizes) go into ``DCIM/Photos``; 15 are deleted (5 from the
middle of the folder, whose index entries get shifted over, and the 10 newest); then 30
tiny notes are written, small enough to live inside their MFT records, so the deleted
photos' MFT records are reused (their names gone from the MFT) while their clusters
stay free. What is left of the photos' names is only in the folder's index ($I30)
slack, and their bytes only for carving: exactly the case E6.2 is for.

Needs WSL ``Ubuntu-24.04`` with root and ``ntfs-3g`` (``apt install ntfs-3g``).

    python tests/fixtures/make_ntfs_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from tests.test_session import noisy_png  # noqa: E402


def sources() -> dict[str, bytes]:
    return {f"IMG_{1000 + i}.png": noisy_png(60 + i * 3, 40 + i, i) for i in range(1, 41)}


def main() -> None:
    files = sources()
    work = tempfile.mkdtemp(prefix="tizo-ntfsfix-")
    for name, data in files.items():
        with open(os.path.join(work, name), "wb") as fh:
            fh.write(data)
    out = os.path.join(HERE, "ntfs-i30.img.gz")
    script = os.path.join(HERE, "make_ntfs_fixture.sh")
    to_wsl = lambda p: subprocess.run(["wsl", "-d", "Ubuntu-24.04", "wslpath", p.replace(os.sep, "/")],  # noqa: E731
                                      capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "bash", to_wsl(script), to_wsl(work), to_wsl(out)],
                   check=True, env=env)
    deleted = {f"DCIM/Photos/IMG_{i}.png": {"size": len(files[f"IMG_{i}.png"]),
                                             "sha256": hashlib.sha256(files[f"IMG_{i}.png"]).hexdigest()}
               for i in [*range(1010, 1015), *range(1031, 1041)]}
    with open(os.path.join(HERE, "ntfs-i30.json"), "w") as fh:
        json.dump(deleted, fh, indent=1)
    print("fixture written:", out)


if __name__ == "__main__":
    main()
