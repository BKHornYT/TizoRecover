"""exFAT: deleted files come back with names, folders and the right bytes."""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import verify
from tizorecover.engine.drives import image_drive
from tizorecover.engine.scan import detect_filesystem
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tests import samples
from tests.exfatimage import ExfatBuilder
from tests.test_session import noisy_png


def _check(label: str, ok: bool, detail: str = "") -> list[str]:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    return [] if ok else [label]


def _build():
    rng = random.Random(3)
    b = ExfatBuilder()
    photos = b.add_dir("Photos")
    old = b.add_dir("Gammelt prosjekt", deleted=True)
    files = {
        "Photos/ferie på Hvaler.png": noisy_png(160, 120, 4),
        "Photos/split.bin": rng.randbytes(50_000),
        "Photos/chain wiped.bin": rng.randbytes(30_000),
        "Gammelt prosjekt/plan.txt": b"plan\n" * 4000,
        "invoice.pdf": samples.make_pdf(2),
        "gone.txt": b"this one was overwritten\n" * 300,
    }
    b.add_file("keep.png", samples.make_png(), into=photos)
    b.add_file("ferie på Hvaler.png", files["Photos/ferie på Hvaler.png"], into=photos, deleted=True)
    b.add_file("split.bin", files["Photos/split.bin"], into=photos, deleted=True, fragmented=True)
    b.add_file("chain wiped.bin", files["Photos/chain wiped.bin"], into=photos, deleted=True,
               fragmented=True, wipe_chain=True)
    b.add_file("plan.txt", files["Gammelt prosjekt/plan.txt"], into=old, deleted=True)
    b.add_file("invoice.pdf", files["invoice.pdf"], deleted=True)
    gone = b.add_file("gone.txt", files["gone.txt"], deleted=True)
    b.overwrite(gone, b"\x00" * 9000)
    return b.build(), files


def test_quick_scan() -> list[str]:
    print("exfat: deleted entry sets come back with names and exact bytes")
    image, files = _build()
    path = os.path.join(tempfile.mkdtemp(prefix="tizo-exfat-"), "exfat.img")
    with open(path, "wb") as fh:
        fh.write(image)
    failures: list[str] = []
    job = ScanJob(image_drive(path), QUICK).start()
    job.wait(60)
    failures += _check("detected as exfat", job.filesystem == "exfat", job.filesystem)
    failures += _check("free space read from the bitmap", job.free_bytes > 0, str(job.free_bytes))
    every = {it.candidate.original_path: it for it in job.items}
    by = {p: it for p, it in every.items() if not it.to_dict()["existing"]}
    failures += _check("only deleted files listed as deleted", "Photos/keep.png" not in by, str(sorted(by)))
    failures += _check("live file listed as Existing", "Photos/keep.png" in every and every["Photos/keep.png"].to_dict()["existing"])
    for rel in ("Photos/ferie på Hvaler.png", "Photos/split.bin", "Gammelt prosjekt/plan.txt", "invoice.pdf"):
        it = by.get(rel)
        same = it is not None and job.data(it).read_all() == files[rel]
        failures += _check(f"{rel} byte-identical", same, it.status if it else "missing")
    split = by.get("Photos/split.bin")
    failures += _check("fragmented file followed through the FAT", split is not None
                       and split.candidate.fragment_count > 1 and not split.candidate.metadata["chain_guessed"])
    wiped = by.get("Photos/chain wiped.bin")
    failures += _check("wiped chain: guessed through free clusters, and right", wiped is not None
                       and wiped.candidate.metadata["chain_guessed"]
                       and job.data(wiped).read_all() == files["Photos/chain wiped.bin"],
                       wiped.status if wiped else "missing")
    plan = by.get("Gammelt prosjekt/plan.txt")
    failures += _check("deleted folder kept", plan is not None and plan.candidate.metadata["folder_deleted"])
    gone = by.get("gone.txt")
    failures += _check("overwritten file marked", gone is not None and gone.status == verify.OVERWRITTEN,
                       gone.status if gone else "missing")
    failures += _check("modified date read", by["invoice.pdf"].candidate.metadata.get("modified") is not None)
    job.close()

    deep = ScanJob(image_drive(path), DEEP).start()
    deep.wait(60)
    named = {it.candidate.original_path for it in deep.items if it.candidate.original_path
             and not it.to_dict()["existing"]}
    carved_dupes = [it for it in deep.items if not it.candidate.original_path and it.candidate.ext in ("png", "pdf")]
    failures += _check("deep scan keeps names, no duplicates", named == set(by) and not carved_dupes,
                       f"{len(carved_dupes)} carved duplicates")
    deep.close()
    return failures


def test_not_exfat() -> list[str]:
    print("exfat: other volumes are not mistaken for exFAT")
    from tests import fsimages
    from tizorecover.engine.formats import ByteSourceView
    from tizorecover.engine.blockdev import open_source
    path = os.path.join(tempfile.mkdtemp(prefix="tizo-exfat-"), "fat.img")
    with open(path, "wb") as fh:
        fh.write(fsimages.Fat32Builder().build())
    src = ByteSourceView(open_source(path))
    return _check("fat32 still fat32", detect_filesystem(src) == "fat32", detect_filesystem(src))


def main() -> int:
    failures = test_quick_scan() + test_not_exfat()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all exfat tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
