"""A quick-formatted NTFS volume: the deep scan reads the old MFT records left in free space.

Uses ``fixtures/ntfs-qformat.img.gz`` (see make_ntfs_qformat_fixture.py): 60 photos, 20 documents
with no file signature and a video, then ``mkntfs -Q`` on top and one new file.
Without the old records, carving can only find the photos, nameless; with them every file whose
record survived comes back with its name, its folder and all its pieces.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.drives import image_drive
from tests import fsimages
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
    with gzip.open(os.path.join(FIX, "ntfs-qformat.img.gz"), "rb") as src:
        fh.write(src.read())
    fh.close()
    return fh.name


def exact(job: ScanJob, want: dict) -> dict[str, object]:
    """Old path -> item, for every item that is one of the old files by name and bytes.

    The folders' own records sat at the start of the old table, which the new one wrote
    over (as Windows' quick format does too), so the folder part is not compared.
    """
    by_name = {p.rsplit("/", 1)[-1]: p for p in want}
    out = {}
    for it in job.snapshot():
        p = by_name.get(it.candidate.name or "")
        if p and hashlib.sha256(job.data(it).read_all()).hexdigest() == want[p]["sha256"]:
            out[p] = it
    return out


def test_quick_finds_nothing_old(path: str, want: dict):
    print("quick scan: the new file table knows nothing of the old files")
    job = ScanJob(image_drive(path), QUICK).start()
    job.wait(60)
    check("no old file in the quick scan", not exact(job, want), str(len(exact(job, want))))
    job.close()


def test_deep_brings_them_back(path: str, want: dict):
    print("deep scan: old records")
    job = ScanJob(image_drive(path), DEEP).start()
    job.wait(180)
    check("scan done", job.state == "done", job.state)
    got = exact(job, want)
    print(f"       {len(got)} of {len(want)} old files back by name, folder and bytes")
    docs = [p for p in want if p.startswith("Documents/")]
    check("documents with no signature are back", all(p in got for p in docs),
          f"{sum(p in got for p in docs)}/{len(docs)}")
    check("video back whole", "Videos/holiday.mov" in got)
    photos = [p for p in want if p.startswith("DCIM/")]
    check("photos back with their names", sum(p in got for p in photos) >= len(photos) - 5,
          f"{sum(p in got for p in photos)}/{len(photos)}")
    carved_twins = [it for it in job.snapshot() if it.candidate.strategy is Strategy.CARVE
                    and it.candidate.ext == "png"]
    check("no nameless carved copy of a named photo left", not carved_twins, f"{len(carved_twins)} left")
    check("a carved photo upgraded in place is reported as changed", len(job.changed) > 0, str(len(job.changed)))
    check("readme.txt (the new file) not counted as an old one", all("readme" not in p for p in got))
    check("records saved for resume", len(job.loose) > 0 and len(job.loose.offsets) == len(job.loose))
    job.close()


def test_planted_fragmented_record(path: str):
    print("an old record of a file in three pieces, out of order")
    rng = random.Random(5)
    cs = 4096
    pieces = [(11010, 4), (11050, 3), (11020, 2)]          # (lcn, clusters), in file order
    size = 9 * cs - 1234
    payload = rng.randbytes(size)
    work = path + ".frag"
    shutil.copyfile(path, work)
    with open(work, "r+b") as fh:
        done = 0
        for lcn, count in pieces:
            fh.seek(lcn * cs)
            fh.write(payload[done:done + count * cs])
            done += count * cs
        rec = fsimages.mft_record(-1, [fsimages.attr_resident(0x10, fsimages.std_info()),
                                       fsimages.attr_resident(0x30, fsimages.file_name_attr("trip.dat", 5, size)),
                                       fsimages.attr_nonresident(0x80, pieces, size, 9 * cs)], in_use=False)
        fh.seek(11090 * cs)
        fh.write(rec)
    try:
        job = ScanJob(image_drive(work), DEEP).start()
        job.wait(180)
        hit = [it for it in job.snapshot() if it.candidate.name == "trip.dat"]
        ok = bool(hit) and job.data(hit[0]).read_all() == payload
        check("trip.dat back byte for byte from its three pieces", ok,
              f"fragments {hit[0].to_dict()['fragments'] if hit else '-'}")
        job.close()
    finally:
        os.unlink(work)


def main() -> int:
    with open(os.path.join(FIX, "ntfs-qformat.json")) as fh:
        want = json.load(fh)
    path = image()
    try:
        test_quick_finds_nothing_old(path, want)
        test_deep_brings_them_back(path, want)
        test_planted_fragmented_record(path)
    finally:
        os.unlink(path)
    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("all quick-format checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
