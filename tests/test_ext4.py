"""ext4: deleted files back by name from the journal; lost volumes list every file.

Uses ``fixtures/ext4-deleted.img.gz``, a real ext4 volume made, filled and
changed by Linux (mkfs.ext4 + the kernel driver; see make_ext4_fixture.py):
a picture, a PDF, a file grown in 6 interleaved pieces and a whole folder were
deleted with ``rm``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.drives import image_drive
from tizorecover.engine.session import DEEP, QUICK, ScanJob

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _check(label: str, ok: bool, detail: str = "") -> list[str]:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    return [] if ok else [label]


def _image() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="tizo-ext4-"), "ext4.img")
    with gzip.open(os.path.join(FIX, "ext4-deleted.img.gz"), "rb") as src, open(path, "wb") as dst:
        dst.write(src.read())
    return path


def test_deleted_from_journal() -> list[str]:
    print("ext4: deleted files (and a deleted folder) come back by name, byte-identical")
    with open(os.path.join(FIX, "ext4-deleted.json")) as fh:
        want = json.load(fh)
    path = _image()
    failures: list[str] = []
    job = ScanJob(image_drive(path), QUICK).start()
    job.wait(60)
    failures += _check("detected", job.filesystem.startswith("ext"), job.filesystem)
    failures += _check("free space read from the block bitmaps", job.free_bytes > 0, str(job.free_bytes))
    by = {it.candidate.original_path: it for it in job.items}
    for rel, digest in want.items():
        it = by.get(rel)
        same = it is not None and hashlib.sha256(job.data(it).read_all()).hexdigest() == digest
        failures += _check(f"{rel}", same, it.status if it else "missing")
    failures += _check("only deleted files listed", set(by) == set(want), str(sorted(set(by) - set(want))))
    frag = by.get("home/user/frag.bin")
    failures += _check("fragmented file mapped in pieces", frag is not None and frag.candidate.fragment_count > 1)
    plan = by.get("home/user/Old/plan.txt")
    failures += _check("deleted folder marked", plan is not None and plan.candidate.metadata.get("folder_deleted"))
    job.close()

    deep = ScanJob(image_drive(path), DEEP).start()
    deep.wait(60)
    carved_png = [it for it in deep.items if not it.candidate.original_path and it.candidate.ext == "png"]
    failures += _check("deep scan adds no duplicate of the named PNG", not carved_png, f"{len(carved_png)} carved")
    deep.close()
    return failures


def test_lost_volume_lists_everything() -> list[str]:
    print("ext4: a lost volume lists its live files too")
    path = _image()
    drive = image_drive(path)
    drive.lost = True
    job = ScanJob(drive, QUICK).start()
    job.wait(60)
    names = {it.candidate.original_path for it in job.items}
    live = {"etc/hostname", "home/user/notes.txt", "home/user/Photos/photo2.png", "home/user/filler.bin"}
    failures = _check("live files listed", live <= names, str(sorted(live - names)))
    failures += _check("deleted ones too", "home/user/report.pdf" in names)
    job.close()
    return failures


def main() -> int:
    failures = test_deleted_from_journal() + test_lost_volume_lists_everything()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all ext4 tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
