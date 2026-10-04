"""Saved scans: save, reopen, resume half way, and refuse a different drive."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import tzscan
from tizorecover.engine.drives import image_drive
from tizorecover.engine.session import DEEP, ScanJob
from tests.ui import demo_image


def _check(label: str, ok: bool, detail: str = "") -> list[str]:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    return [] if ok else [label]


def _keys(items) -> set:
    return {(it.candidate.data_offset, it.candidate.size, it.candidate.ext) for it in items}


def test_save_reopen_resume() -> list[str]:
    print("tzscan: a deep scan saves itself, reopens, and resumes from half way")
    work = tempfile.mkdtemp(prefix="tizo-tzscan-")
    image = demo_image.write(os.path.join(work, "demo.img"))
    drive = image_drive(image)
    save_to = os.path.join(work, "demo.tzscan")
    failures: list[str] = []

    full = ScanJob(drive, DEEP, autosave=save_to).start()
    full.wait(60)
    failures += _check("full scan done", full.state == "done", full.state)
    failures += _check("saved on finish", os.path.isfile(save_to) and os.path.isfile(save_to + ".info"))
    want = _keys(full.items)
    carved = [it for it in full.items if it.candidate.strategy.value == "carve"]
    first_bytes = full.data(full.items[0]).read_all() if full.items else b""
    full.close()

    body = tzscan.load(save_to)
    info = tzscan.summary(save_to)
    failures += _check("summary", info["found"] == len(want) and info["state"] == "done",
                       f"{info['found']} files, {info['state']}")

    reopened = ScanJob(drive, DEEP, resume=body).start()
    reopened.wait(30)
    failures += _check("finished scan reopens without scanning", reopened.state == "done"
                       and _keys(reopened.items) == want and reopened.progress.stage == "done")
    same = bool(reopened.items) and reopened.data(reopened.items[0]).read_all() == first_bytes
    failures += _check("reopened file reads the same bytes", same)
    reopened.close()

    # Pretend the scan was stopped half way through the content search.
    half = body["deep"]["total"] // 2
    cut = sorted(carved, key=lambda it: it.candidate.data_offset)
    keep = [it for it in body["items"] if it["candidate"]["strategy"] != "carve"
            or it["candidate"]["data_offset"] + it["candidate"]["size"] <= half]
    partial = {**body, "state": "stopped", "items": keep,
               "deep": {"done": half, "total": body["deep"]["total"],
                        "last_carve_end": max([it["candidate"]["data_offset"] + it["candidate"]["size"]
                                               for it in keep if it["candidate"]["strategy"] == "carve"]
                                              or [0])}}
    resumed = ScanJob(drive, DEEP, resume=partial).start()
    resumed.wait(60)
    got = _keys(resumed.items)
    failures += _check("resumed scan finds the same files", got == want,
                       f"{len(got)} vs {len(want)}; missing {sorted(want - got)[:3]} extra {sorted(got - want)[:3]}")
    failures += _check("no duplicates", len(resumed.items) == len(got))
    failures += _check("carved before and after the cut", len(cut) >= 2)
    resumed.close()

    other = {**body, "fingerprint": "0" * 32}
    wrong = ScanJob(drive, DEEP, resume=other, autosave=save_to).start()
    wrong.wait(30)
    failures += _check("other drive refused", wrong.state == "failed" and wrong.problems, wrong.state)
    failures += _check("refused scan does not overwrite the save", tzscan.load(save_to)["fingerprint"]
                       == body["fingerprint"])
    wrong.close()
    return failures


def main() -> int:
    failures = test_save_reopen_resume()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all tzscan tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
