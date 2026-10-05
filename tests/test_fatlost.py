"""A quick-formatted FAT32 volume: the deep scan finds the old folders in free space (TestDisk's method).

Uses ``fixtures/fat-lostdirs.img.gz`` (see make_fat_lostdirs_fixture.py): DCIM/100MEDIA photos, documents
with no signature and music, then ``mkfs.vfat`` on top and one new file. Before: carving alone brings the
photos back nameless and the rest not at all. Now: every file with its name, in its folder.
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
from tizorecover.engine.results import Strategy
from tizorecover.engine.session import DEEP, QUICK, ScanJob

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(label)


def image() -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    with gzip.open(os.path.join(FIX, "fat-lostdirs.img.gz"), "rb") as src:
        fh.write(src.read())
    fh.close()
    return fh.name


def found(job: ScanJob, want: dict) -> dict[str, object]:
    """Old path -> item, for items that are an old file by name and bytes."""
    by_name = {p.rsplit("/", 1)[-1]: p for p in want}
    out = {}
    for it in job.snapshot():
        p = by_name.get(it.candidate.name or "")
        if p and hashlib.sha256(job.data(it).read_all()).hexdigest() == want[p]["sha256"]:
            out[p] = it
    return out


def main() -> int:
    with open(os.path.join(FIX, "fat-lostdirs.json")) as fh:
        want = json.load(fh)
    path = image()
    try:
        print("quick scan: the new FAT knows nothing of the old files")
        job = ScanJob(image_drive(path), QUICK).start()
        job.wait(60)
        check("no old file in the quick scan", not found(job, want))
        job.close()

        print("deep scan: lost folders")
        job = ScanJob(image_drive(path), DEEP).start()
        job.wait(180)
        check("scan done", job.state == "done", job.state)
        got = found(job, want)
        print(f"       {len(got)} of {len(want)} old files back by name and bytes, {len(job.loose)} lost folders")
        check("every old file back", len(got) == len(want), f"{len(got)}/{len(want)}")
        paths = {p: (it.candidate.original_path or "") for p, it in got.items()}
        check("subfolders keep their names", all(v.endswith(p.split("/", 1)[1]) for p, v in paths.items()
                                                 if p.startswith("Documents/")), str(list(paths.values())[:2]))
        # DCIM's own cluster went to today's readme.txt: 100MEDIA's name was in it, so both are Lost<n>.
        check("folders whose names are gone are Lost<n>",
              all("/Lost" in v for p, v in paths.items() if p.startswith("DCIM/")))
        check("top folders whose name was in the old root are Orphans/Lost<n>",
              all(v.startswith("Orphans/Lost") for v in paths.values()), str(list(paths.values())[:2]))
        twins = [it for it in job.snapshot() if it.candidate.strategy is Strategy.CARVE and it.candidate.ext == "png"]
        check("no nameless carved copy of a named photo", not twins, f"{len(twins)} left")
        check("readme.txt (today's file) not taken for an old one", all("readme" not in p for p in got))
        job.close()
    finally:
        os.unlink(path)
    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("all FAT lost-folder checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
