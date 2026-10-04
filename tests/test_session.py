"""TizoRecover's scan job end to end, plus the engine fixes it depends on."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import verify
from tizorecover.engine.access import CandidateData
from tizorecover.engine.drives import image_drive
from tizorecover.engine.fs import ntfs
from tizorecover.engine.results import FileCandidate, Strategy
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tizorecover.engine.writer import save_items
from tests import fsimages, samples


def _image_file(data: bytes) -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    fh.write(data)
    fh.close()
    return fh.name


def _run(builder, mode=QUICK) -> tuple[ScanJob, str]:
    path = _image_file(builder.build())
    job = ScanJob(image_drive(path), mode).start()
    job.wait(60)
    return job, path


def noisy_png(width: int = 120, height: int = 100, seed: int = 7) -> bytes:
    """A PNG that does not compress: stored zlib blocks of random pixels."""
    import random
    import struct
    import zlib
    rng = random.Random(seed)
    rows = b"".join(b"\x00" + bytes(rng.getrandbits(8) for _ in range(width * 3))
                    for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + samples._png_chunk(b"IHDR", ihdr)
            + samples._png_chunk(b"IDAT", zlib.compress(rows, 0))
            + samples._png_chunk(b"IEND", b""))


def _check(label: str, ok: bool, detail: str = "") -> list[str]:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    return [] if ok else [label]


def test_fat_live_folder_and_freed_chain():
    print("session: FAT deleted files in a live folder, chains freed like Windows does")
    b = fsimages.Fat32Builder()
    photos = b.add_dir("Photos")
    big = noisy_png()
    small = b"hello from a deleted note\n" * 3
    b.add_live_file("keep.txt", b"still here", into=photos)
    b.add_deleted_file("Holiday 2026.png", big, into=photos, free_chain=True)
    b.add_deleted_file("note.txt", small, free_chain=True)
    job, path = _run(b)
    try:
        by_name = {it.candidate.name: it for it in job.items}
        failures = []
        failures += _check("job finished", job.state == "done", f"state={job.state} {job.problems}")
        png = by_name.get("Holiday 2026.png")
        failures += _check("file in a live folder found", png is not None,
                           f"names={sorted(by_name)}")
        if png is not None:
            data = job.data(png).read_all()
            failures += _check("multi-cluster file byte-identical after its chain was freed",
                               data == big, f"{len(data)} of {len(big)} bytes, "
                               f"{len(png.candidate.metadata['chain'])} clusters")
            failures += _check("folder kept", png.candidate.original_path == "Photos/Holiday 2026.png",
                               png.candidate.original_path or "")
            failures += _check("status good", png.status == verify.GOOD, f"{png.status} {png.notes}")
        note = by_name.get("note.txt")
        failures += _check("root file found", note is not None and job.data(note).read_all() == small)
        keep = by_name.get("keep.txt")
        failures += _check("live file listed as Existing, not deleted",
                           keep is not None and keep.to_dict()["existing"] and keep.status == verify.GOOD)
        return failures
    finally:
        job.close()
        os.unlink(path)


def test_save_items_streams_and_never_overwrites():
    print("session: saving streams files out and never overwrites")
    b = fsimages.Fat32Builder()
    payload = samples.make_png(200, 150)
    b.add_deleted_file("pic.png", payload, free_chain=True)
    job, path = _run(b)
    out = tempfile.mkdtemp()
    try:
        items = job.snapshot()
        first = save_items(items, job.data, out)
        second = save_items(items, job.data, out)
        failures = []
        ok = first and first[0][2] and open(first[0][1], "rb").read() == payload
        failures += _check("saved byte-identical", bool(ok), first[0][1] if first else "")
        failures += _check("second save got a new name",
                           second and second[0][1] != first[0][1] and second[0][1].endswith("pic (1).png"),
                           second[0][1] if second else "")
        return failures
    finally:
        job.close()
        os.unlink(path)


def test_deep_scan_finds_content_without_a_name():
    print("session: deep scan finds a file whose directory entry is gone")
    b = fsimages.Fat32Builder()
    payload = noisy_png(140, 110, seed=3)
    start = b.add_deleted_file("gone.png", payload, free_chain=True)
    image = bytearray(b.build())
    # Wipe its directory entry (and the long-name slots before it), so only
    # the bytes are left for the carver to find.
    import struct
    for i in range(0, len(image) - 32, 32):
        slot = image[i:i + 32]
        if slot[0] == 0xE5 and slot[0x0B] == 0x20 and struct.unpack_from("<H", slot, 0x1A)[0] == start:
            j = i
            while j >= 32 and image[j - 32 + 0x0B] == 0x0F:
                j -= 32
            image[j:i + 32] = b"\x00" * (i + 32 - j)
    path = _image_file(bytes(image))
    job = ScanJob(image_drive(path), DEEP).start()
    job.wait(60)
    try:
        carved = [it for it in job.items if it.candidate.strategy is Strategy.CARVE
                  and it.candidate.ext == "png"]
        failures = _check("job finished", job.state == "done", f"{job.state} {job.problems}")
        failures += _check("png carved from free space", bool(carved),
                           f"items={[(i.candidate.ext, i.candidate.strategy.value) for i in job.items]}")
        if carved:
            failures += _check("carved bytes identical", job.data(carved[0]).read_all() == payload)
            failures += _check("carved file is in the free clusters",
                               carved[0].candidate.data_offset >= 0, f"start cluster {start}")
        return failures
    finally:
        job.close()
        os.unlink(path)


def test_sparse_runs_and_extents():
    print("engine: NTFS sparse runs read as zeros, extents merge")
    # header 0x01 = 1-byte length, no offset -> sparse run of 4 clusters
    runs = ntfs.parse_runs(bytes([0x11, 0x02, 0x10, 0x01, 0x04, 0x11, 0x02, 0x02, 0x00]))
    extents = ntfs.runs_to_extents(runs, 4096, 8 * 4096)
    failures = _check("sparse run marked", runs[1][1] == ntfs.SPARSE, str(runs))
    failures += _check("extents", extents == [(0x10 * 4096, 2 * 4096), (-1, 4 * 4096),
                                               (0x12 * 4096, 2 * 4096)], str(extents))

    class Src:
        size = 1 << 30

        def at(self, off, n):
            return bytes([0xAB]) * n

    cand = FileCandidate(ext="bin", size=8 * 4096, data_offset=-1, strategy=Strategy.NTFS,
                         metadata={"extents": extents})
    data = CandidateData(cand, Src())
    blob = data.read_all()
    failures += _check("hole is zeros, data is data",
                       blob[:8192] == b"\xab" * 8192 and blob[8192:8192 + 16384] == b"\x00" * 16384
                       and blob[-8192:] == b"\xab" * 8192 and len(blob) == 8 * 4096)
    failures += _check("read across a piece boundary",
                       data.at(8192 - 2, 4) == b"\xab\xab\x00\x00")
    return failures


def test_deleted_short_name():
    print("engine: deleted 8.3 names keep their extension")
    from tizorecover.engine.fs import fat
    slot = bytearray(32)
    slot[0:11] = b"\xe5HOTO   JPG"
    slot[0x0B] = 0x20
    entries = fat.parse_dir_entries(bytes(slot))
    return _check("short name", entries and entries[0].short_name == "_HOTO.JPG",
                  entries[0].short_name if entries else "")


if __name__ == "__main__":
    failures: list[str] = []
    for test in (test_fat_live_folder_and_freed_chain, test_save_items_streams_and_never_overwrites,
                 test_deep_scan_finds_content_without_a_name, test_sparse_runs_and_extents,
                 test_deleted_short_name):
        failures += test()
    if failures:
        print(f"\nFAILURES ({len(failures)}): {failures}")
        sys.exit(1)
    print("\nall session tests passed")
