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


# A real 48x36 JPEG (made with System.Drawing): the samples module's JPEG has the
# right structure for carving, but a browser cannot draw it.
REAL_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYU"
    "GBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAAkADAD"
    "ASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKB"
    "kaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQF"
    "BgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX"
    "2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD6wqG8vbfTrZ7i7nitbdMbpZnCIuTgZJ4HJAqavnf4z+MJNd8SS6bDK39n6e3l+WCQ"
    "rzDIdiMDkZKjr0JH3jXwGR5PPOsX7CLtFK8n2X+b6ff0P0jPs5p5JhPbyXNJu0V3f+S6/d1PQrz48eGrW5eKOO+u0XGJoYVCNx23Mp9uQOlT6R8b"
    "/DWqXi27tdafuwFlu41EZJIABKs2OucnAGDk1850V+uvgjKnDlXNfvf8drfgfj645zVT5ny27W09N7/ifZEE8dzDHNDIssUih0kRgVZSMggjqDT6"
    "8Q+BHjCSG/k8P3MrPBMpktFYkhHGS6jjgEZbkgAqe7V7fX45nGV1MoxksLN3W6fdPZ/o/NM/Z8mzWnnGDjiqas9muzW6/VeTQV8neNLWay8XazDO"
    "ZWlF3KS8yhXcFiQxAAHzAg8ADnjivrGvMPiz8L7jxPMmraQqtqCqsc1sdqecoPDBjj5hnByeQBjGMH6Hg/NKGXY2UcQ1GM1a76NbXfRf8C585xll"
    "VfMsFGeHTlKm72XVPey6tffvY8Doqe8srjTrl7e7gltbhMbopkKOuRkZB5HBBqbSNGvtevFtNPtZbu4bHyRLnAyBknoBkjk4AzX766tOMPaOSUd7"
    "30t3ufz6qVSU/ZRi3La1tb9rHU/BqCSX4iaayRs6xLK7sqkhF8phk+gyQPqRX0rXB/Cr4dt4LsJbm9Ktqt2oDqACIFHOwN3J6tg4yBjOMnvK/nfi"
    "vMqOZZi50HeMUop97Ntv73bztc/o7hLLa2WZaoV1aU25NdrpJL7lfyvYKKKK+OPswooooAKKKKAP/9k="
)


def preview_jpeg() -> bytes:
    """A real JPEG padded past 2 KB with a comment segment (previews smaller are ignored)."""
    import base64
    jpeg = base64.b64decode(REAL_JPEG_B64)
    comment = b"embedded camera preview " * 120
    return jpeg[:2] + b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment + jpeg[2:]


def fake_raw() -> bytes:
    """What a camera RAW looks like to the preview: a TIFF header, sensor data, a JPEG inside."""
    import random
    rng = random.Random(42)
    return b"II*\x00\x08\x00\x00\x00" + rng.randbytes(20_000) + preview_jpeg() + rng.randbytes(9_000)


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
    b.add_deleted_file("DSC_0420.nef", fake_raw(), into=trip, free_chain=True)
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
