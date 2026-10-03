"""FAT32 undelete tests against a hand-built volume."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.blockdev import FileBlockReader
from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.fs import fat
from tizorecover.engine.results import Strategy
from tizorecover.engine.access import read_all
from tests import fsimages, samples


def _scan(builder: fsimages.Fat32Builder):
    image = builder.build()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        reader = FileBlockReader(path, "fat-test")
        try:
            src = ByteSourceView(reader)
            found = list(fat.recover_fat(src, "fat-test"))
            for c in found:
                c.metadata["inline_data"] = read_all(c, src)
            return found, image
        finally:
            reader.close()
    finally:
        os.unlink(path)


def test_geometry():
    print("fat: volume geometry parsed")
    image = fsimages.Fat32Builder().build()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        reader = FileBlockReader(path)
        try:
            info = fat.find_fat(ByteSourceView(reader))
        finally:
            reader.close()
    finally:
        os.unlink(path)
    ok = info is not None and info.cluster_size == 4096 and info.bits == 32
    print(f"  {'ok  ' if ok else 'FAIL'} cluster={info.cluster_size if info else '?'} "
          f"bits={info.bits if info else '?'} root_cluster={info.root_cluster if info else '?'} "
          f"clusters={info.cluster_count if info else '?'}")
    return [] if ok else ["fat geometry not parsed"]


def test_deleted_file_with_long_name():
    print("fat: deleted file recovers with its long name")
    b = fsimages.Fat32Builder()
    payload = samples.make_png(120, 90)
    b.add_deleted_file("Sunset over the harbour.png", payload)
    found, _ = _scan(b)
    hits = [c for c in found if "Sunset" in (c.name or "")]
    if not hits:
        print(f"  FAIL nothing recovered; got {[(c.name, c.short) for c in found]}")
        return ["deleted file missing"]
    c = hits[0]
    exact = c.metadata["inline_data"] == payload
    ok = exact and c.name == "Sunset over the harbour.png" and c.strategy is Strategy.FAT
    print(f"  {'ok  ' if ok else 'FAIL'} name={c.name!r} size={c.size} match={exact} "
          f"chain={c.metadata['chain']}")
    print(f"       reasons: {c.reasons}")
    return [] if ok else ["long name wrong"]


def test_live_excluded():
    print("fat: live files are not reported")
    b = fsimages.Fat32Builder()
    b.add_live_file("present.txt", b"still here")
    b.add_deleted_file("gone.txt", b"deleted content")
    found, _ = _scan(b)
    names = [c.name for c in found]
    ok = names == ["gone.txt"]
    print(f"  {'ok  ' if ok else 'FAIL'} recovered={names}")
    return [] if ok else ["live file leaked"]


def test_deleted_subdirectory():
    print("fat: files inside a deleted folder come back with the folder path")
    b = fsimages.Fat32Builder()
    b.add_live_file("root-file.txt", b"kept")
    sub = b.add_dir("Archive", deleted=True)
    payload = samples.make_zip(2)
    b.add_deleted_file("report.pdf", payload, into=sub)
    b.add_dir("Nested", deleted=False, into=sub)
    found, _ = _scan(b)
    hits = [c for c in found if c.name == "report.pdf"]
    if not hits:
        print(f"  FAIL not found; got {[(c.name, c.original_path) for c in found]}")
        return ["deleted subdir contents missing"]
    c = hits[0]
    ok = c.original_path == "Archive/report.pdf" and c.metadata["inline_data"] == payload
    print(f"  {'ok  ' if ok else 'FAIL'} path={c.original_path!r} size={c.size} "
          f"match={c.metadata['inline_data'] == payload}")
    return [] if ok else ["subdir path wrong"]


def test_multi_cluster_chain():
    print("fat: multi-cluster file reassembled from its chain")
    b = fsimages.Fat32Builder()
    payload = samples.make_jpeg(300, 300) + b"\x00" * 9000
    b.add_deleted_file("big.jpg", payload)
    found, _ = _scan(b)
    hits = [c for c in found if c.name == "big.jpg"]
    if not hits:
        return ["chain file missing"]
    c = hits[0]
    ok = len(c.metadata["chain"]) > 1 and c.metadata["inline_data"] == payload
    print(f"  {'ok  ' if ok else 'FAIL'} clusters={len(c.metadata['chain'])} size={c.size} "
          f"of {len(payload)} match={c.metadata['inline_data'] == payload}")
    return [] if ok else ["chain reassembly wrong"]


def main() -> int:
    failures: list[str] = []
    for test in (
        test_geometry,
        test_deleted_file_with_long_name,
        test_live_excluded,
        test_multi_cluster_chain,
        test_deleted_subdirectory,
    ):
        failures.extend(test())
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all fat tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
