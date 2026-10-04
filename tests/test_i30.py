"""NTFS index ($I30) leftovers: names of deleted files whose MFT record was already reused.

Uses ``fixtures/ntfs-i30.img.gz``, a real NTFS volume made and changed by ntfs-3g (see
make_ntfs_fixture.py): 40 PNGs in DCIM/Photos, 5 deleted from the middle of the folder and the
10 newest deleted, then 30 tiny notes that reuse the freed MFT records. The 10 newest leave
their names in the index blocks' unused tails (two of them behind a rewritten end marker);
the 5 from the middle are shifted over and gone, as on a real drive.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.blockdev import open_source
from tizorecover.engine.drives import image_drive
from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.fs import ntfs
from tizorecover.engine.results import FileCandidate, Strategy
from tizorecover.engine.session import DEEP, LockedSource, ScanJob

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
failures: list[str] = []
TAIL = [f"DCIM/Photos/IMG_{i}.png" for i in range(1031, 1041)]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(label)


def image() -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    with gzip.open(os.path.join(FIX, "ntfs-i30.img.gz"), "rb") as src:
        fh.write(src.read())
    fh.close()
    return fh.name


def test_leftovers(path: str, want: dict):
    print("index leftovers")
    src = LockedSource(ByteSourceView(open_source(path)))
    ghosts: list[dict] = []
    deleted_by_mft = list(ntfs.recover_ntfs(src, "t", ghosts=ghosts))
    paths = sorted(g["path"] for g in ghosts)
    check("MFT walk alone finds none of them (records reused)", not any(c.original_path in want for c in deleted_by_mft))
    check("all 10 newest names found in the index tails", paths == TAIL, str([p.split('/')[-1] for p in paths]))
    check("sizes exact", all(g["size"] == want[g["path"]]["size"] for g in ghosts if g["path"] in want))
    check("no live file reported as deleted", all(g["path"] in want for g in ghosts))
    check("dates kept", all(g.get("modified") for g in ghosts))


def test_scan(path: str, want: dict):
    print("deep scan matches carved files to the names")
    job = ScanJob(image_drive(path), DEEP).start()
    job.wait(180)
    named = {it.candidate.original_path: it for it in job.snapshot()
             if it.candidate.metadata.get("named_from") == "ntfs-index"}
    check("scan done", job.state == "done", job.state)
    # IMG_1036's own clusters were reused by the growing index: its bytes are gone, nothing can bring it back.
    expect = [p for p in TAIL if not p.endswith("IMG_1036.png")]
    check("9 carved photos got their names and folder back", sorted(named) == expect, str(sorted(named)))
    same = sum(hashlib.sha256(job.data(it).read_all()).hexdigest() == want[p]["sha256"] for p, it in named.items())
    check("byte-identical", same == len(named), f"{same}/{len(named)}")
    check("shown under the old folder", all(it.to_dict()["named"] for it in named.values()))
    job.close()


def test_ambiguous_size_not_matched():
    print("ambiguous matches are refused")
    job = ScanJob.__new__(ScanJob)
    job._set_ghosts([{"name": "a.png", "path": "a.png", "size": 1000, "ext": "png"},
                     {"name": "b.png", "path": "b.png", "size": 1000, "ext": "png"},
                     {"name": "c.png", "path": "c.png", "size": 2000, "ext": "png"}])
    one = FileCandidate(ext="png", size=1000, data_offset=0, strategy=Strategy.CARVE)
    two = FileCandidate(ext="png", size=2000, data_offset=0, strategy=Strategy.CARVE)
    jpg = FileCandidate(ext="jpg", size=2000, data_offset=0, strategy=Strategy.CARVE)
    check("two leftovers with the same size: no name", not job._name_from_ghost(one))
    check("other type, same size: no name", not job._name_from_ghost(jpg))
    check("unique size + type: named", job._name_from_ghost(two) and two.original_path == "c.png")
    check("a leftover is used once", not job._name_from_ghost(FileCandidate(ext="png", size=2000, data_offset=0,
                                                                               strategy=Strategy.CARVE)))


def main() -> int:
    with open(os.path.join(FIX, "ntfs-i30.json"), encoding="utf-8") as fh:
        want = json.load(fh)
    path = image()
    test_leftovers(path, want)
    test_scan(path, want)
    test_ambiguous_size_not_matched()
    os.unlink(path)
    print()
    if failures:
        print(f"{len(failures)} $I30 checks FAILED")
        return 1
    print("all $I30 checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
