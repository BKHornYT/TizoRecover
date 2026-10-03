"""End-to-end: synthetic volume -> scan -> write files out -> verify bytes."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import scan as rscan
from tizorecover.engine.writer import safe_component, save, safe_path
from tests import fsimages, samples


def _image(builder) -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    fh.write(builder.build())
    fh.close()
    return fh.name


def test_ntfs_end_to_end():
    print("e2e: NTFS volume -> files on disk")
    png = samples.make_png(140, 110)
    text = b"the quick brown fox jumps over the lazy dog"
    b = fsimages.NtfsBuilder()
    docs = b.add_dir("Documents", parent_index=5)
    b.add_deleted_file("holiday.png", png, parent_index=docs)
    b.add_deleted_file("notes.txt", text, resident=True, parent_index=docs)
    image = _image(b)
    out = tempfile.mkdtemp()
    try:
        report = rscan.scan_device(image, target="C:/fake/Documents")
        assert report.filesystem == "ntfs", report.filesystem
        saved = save(report, out)
        ok = [p for _, p, good in saved if good]
        names = {os.path.basename(p) for p in ok}
        problems = [f"{p}" for p in report.problems if p.fatal]
        assert "holiday.png" in names, names
        assert "notes.txt" in names, names
        holiday = next(p for p in ok if p.endswith("holiday.png"))
        with open(holiday, "rb") as fh:
            assert fh.read() == png, "png bytes differ"
        notes = next(p for p in ok if p.endswith("notes.txt"))
        with open(notes, "rb") as fh:
            assert fh.read() == text, "text bytes differ"
        assert holiday.endswith(os.path.join("Documents", "holiday.png")), holiday
        print(f"  ok   {len(ok)} file(s) written, paths preserved, bytes exact")
        print(f"       {' | '.join(sorted(names))}")
        if problems:
            print(f"       fatal problems: {problems}")
    finally:
        shutil.rmtree(out, ignore_errors=True)
        os.unlink(image)
    return []


def test_carved_only_volume():
    print("e2e: volume with no filesystem metadata -> carving still works")
    jpg = samples.make_jpeg(200, 150)
    doc = samples.make_docx()
    body = bytearray(b"\x00" * 4096)
    body[1000:1000 + len(jpg)] = jpg
    body[20000:20000 + len(doc)] = doc
    b = fsimages.Fat32Builder()
    b.add_deleted_file("photo.jpg", jpg)
    b.add_deleted_file("essay.docx", doc)
    image = _image(b)
    out = tempfile.mkdtemp()
    try:
        report = rscan.scan_device(image, target="D:/", strategies=["ntfs"],
                                   include_orphans=False)
        assert report.filesystem == "fat32", report.filesystem
        assert any("not NTFS" in p.message for p in report.problems), \
            f"scanning a FAT volume as NTFS should be reported: {report.problems}"
        report = rscan.scan_device(image, target="D:/", strategies=["carve"],
                                   include_orphans=False)
        saved = save(report, out)
        carved = [p for _, p, success in saved if success]
        matched = 0
        for path in carved:
            with open(path, "rb") as fh:
                data = fh.read()
            if data in (jpg, doc):
                matched += 1
        good = matched == 2
        print(f"  {'ok  ' if good else 'FAIL'} carved {len(carved)} file(s), "
              f"{matched}/2 byte-exact")
        return [] if good else ["carved content mismatch"]
    finally:
        shutil.rmtree(out, ignore_errors=True)
        os.unlink(image)


def test_duplicates_collapse():
    print("e2e: the same file found twice is written once")
    png = samples.make_png(90, 90)
    b = fsimages.NtfsBuilder()
    b.add_dir("Documents", parent_index=5)
    b.add_deleted_file("holiday.png", png)
    image = _image(b)
    out = tempfile.mkdtemp()
    try:
        report = rscan.scan_device(image, target="C:/fake/Documents")
        before = len(report.candidates)
        saved = save(report, out)
        ok = [p for _, p, good in saved if good]
        files = [p for p in ok if p.endswith(".png")]
        good = len(files) == 1
        print(f"  {'ok  ' if good else 'FAIL'} {before} candidate(s) -> {len(files)} file(s) on disk")
        return [] if good else ["duplicate not collapsed"]
    finally:
        shutil.rmtree(out, ignore_errors=True)
        os.unlink(image)


def test_name_safety():
    print("e2e: hostile names cannot escape the output folder")
    cases = [
        ("../../etc/passwd", ".._.._etc_passwd"),
        ('a<b>c:d"e|f?g*h.txt', "a_b_c_d_e_f_g_h.txt"),
        ("CON", "_CON"),
        ("trailing.  ", "trailing"),
        ("..", "_"),
        (".gitignore", ".gitignore"),
        ("", "_"),
    ]
    bad = []
    for raw, expected in cases:
        got = safe_component(raw)
        if got != expected:
            bad.append(f"{raw!r} -> {got!r} (wanted {expected!r})")
    joined = safe_path("Documents/../../Windows/System32/evil.dll", "x")
    escapes = os.path.isabs(joined) or ".." in joined.split(os.sep)
    for c in bad:
        print(f"  FAIL {c}")
    if escapes:
        print(f"  FAIL path traversal not neutralised: {joined!r}")
    print(f"  {'ok  ' if not bad and not escapes else 'FAIL'} "
          f"{len(cases)} name case(s), traversal blocked")
    return bad + (["traversal"] if escapes else [])


def main() -> int:
    failures: list[str] = []
    for test in (test_ntfs_end_to_end, test_carved_only_volume,
                 test_duplicates_collapse, test_name_safety):
        try:
            failures.extend(test())
        except AssertionError as exc:
            print(f"  FAIL assertion: {exc}")
            failures.append(str(exc))
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all end-to-end tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
