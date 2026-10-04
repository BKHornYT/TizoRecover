"""A small FAT32 image that exercises every part of the review screen.

Deleted files in live and deleted folders (named, high chances), a deleted file
whose clusters a live file took over (low chances), and orphan files in free
space that only the content search finds (the Reconstructed tab).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests import fsimages, samples  # noqa: E402
from tests.test_session import noisy_png  # noqa: E402


def build() -> bytes:
    b = fsimages.Fat32Builder()
    photos = b.add_dir("Photos")
    trip = b.add_dir("Iceland 2026", into=photos)
    docs = b.add_dir("Documents")
    old = b.add_dir("Old project", deleted=True)
    music = b.add_dir("Music")

    b.add_live_file("readme.txt", b"this one still exists\n")
    for i in range(6):
        b.add_deleted_file(f"IMG_{2040 + i}.png", noisy_png(90 + i * 7, 70 + i * 5, seed=i), into=trip,
                           free_chain=True)
    b.add_deleted_file("cover.jpg", samples.make_jpeg(48, 48), into=photos, free_chain=True)
    b.add_deleted_file("logo.png", samples.make_png(64, 48, b"\xfa\xb2\x83"), into=photos, free_chain=True)
    b.add_live_file("keep.png", samples.make_png(), into=photos)
    b.add_deleted_file("Budget 2026.docx", samples.make_docx(), into=docs, free_chain=True)
    b.add_deleted_file("Invoice 1042.pdf", samples.make_pdf(2), into=docs, free_chain=True)
    b.add_deleted_file("notes.txt", b"Shopping list\n- milk\n- coffee\n" * 20, into=docs, free_chain=True)
    b.add_deleted_file("plan.txt", b"Phase 1: everything.\n" * 40, into=old, free_chain=True)
    b.add_deleted_file("data.db", samples.make_sqlite(4), into=old, free_chain=True)
    b.add_deleted_file("voice memo.wav", samples.make_wav(9000), into=music, free_chain=True)
    b.add_deleted_file("archive.zip", samples.make_zip(4), free_chain=True)

    # Low chances: a deleted entry whose first cluster now belongs to a live file.
    live_start, _ = b._allocate(b"new data that replaced the old file\n" * 30)
    from tizorecover.engine.fs import fat  # noqa: F401  (keeps the import cost honest)
    buf = b._buffer(docs)
    for slot in fsimages._lfn_slots("old report.pdf"):
        buf += slot
    buf += fsimages._short_entry("old report.pdf", live_start, 900, 0x20, deleted=True)
    buf2 = b._buffer(None)
    for slot in fsimages._lfn_slots("taken.txt"):
        buf2 += slot
    buf2 += fsimages._short_entry("taken.txt", live_start, 1080, 0x20, deleted=False)

    # Orphans in free space: no directory entry anywhere, only content.
    for payload in (samples.make_jpeg(40, 40), noisy_png(60, 50, seed=99), samples.make_pdf(1),
                    samples.make_gif(), samples.make_mp4(4096), samples.make_wav(3000),
                    samples.make_gzip(), samples.make_bmp(16, 16)):
        start, count = b._allocate(payload)
        for i in range(count):
            fsimages._fat_entry(b.image, start + i, 0)
    return b.build()


def write(path: str) -> str:
    with open(path, "wb") as fh:
        fh.write(build())
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else "demo.img"))
