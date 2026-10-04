"""Lost partitions: deleted from the table, or quick-formatted over."""

from __future__ import annotations

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.blockdev import open_source
from tizorecover.engine.drives import Drive
from tizorecover.engine.partitions import Searcher
from tizorecover.engine.session import QUICK, ScanJob
from tests import fsimages, samples
from tests.exfatimage import ExfatBuilder
from tests.test_session import noisy_png

MIB = 1 << 20


def _check(label: str, ok: bool, detail: str = "") -> list[str]:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    return [] if ok else [label]


def _ext_superblock(group: int, blocks: int = 65536, per_group: int = 32768) -> bytes:
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x04, blocks)
    struct.pack_into("<I", sb, 0x18, 2)                 # 4 KiB blocks
    struct.pack_into("<I", sb, 0x20, per_group)
    sb[0x38:0x3A] = b"\x53\xef"
    struct.pack_into("<H", sb, 0x3A, 1)
    struct.pack_into("<H", sb, 0x5A, group)
    struct.pack_into("<I", sb, 0x60, 0x40)              # extents: ext4
    sb[0x68:0x78] = bytes(range(16))
    sb[0x78:0x80] = b"rootfs\x00\x00"
    return bytes(sb)


def build_disk() -> tuple[bytes, dict]:
    """A disk with an empty partition table and four file systems on it."""
    disk = bytearray(400 * MIB)
    fat = fsimages.Fat32Builder()
    fat.add_deleted_file("old photo.png", noisy_png(80, 60, 9), free_chain=True)
    fat_img = fat.build()
    disk[1 * MIB:1 * MIB + len(fat_img)] = fat_img

    ex = ExfatBuilder()
    ex.add_file("report.pdf", samples.make_pdf(2), deleted=True)
    ex_img = ex.build()
    disk[32 * MIB:32 * MIB + len(ex_img)] = ex_img

    # NTFS at 64 MiB, then "quick formatted": its first sector now holds something else.
    nt = fsimages.NtfsBuilder()
    secret = noisy_png(90, 70, 11)
    nt.add_deleted_file("before the format.png", secret)
    nt.add_live_file("still there when formatted.txt", b"a file nobody deleted\n" * 200)
    nt_img = bytearray(nt.build())
    nt_start = 64 * MIB
    disk[nt_start:nt_start + len(nt_img)] = nt_img
    disk[nt_start + len(nt_img):nt_start + len(nt_img) + 512] = nt_img[:512]   # backup boot sector
    disk[nt_start:nt_start + 512] = bytes(512)                                # first one wiped

    # ext4 at 130 MiB whose primary superblock is gone; group 1's copy at +128 MiB survives.
    ext_start = 130 * MIB
    disk[ext_start + 128 * MIB:ext_start + 128 * MIB + 1024] = _ext_superblock(group=1)
    return bytes(disk), {"fat32": 1 * MIB, "exfat": 32 * MIB, "ntfs": nt_start, "ext4": ext_start,
                         "ntfs_size": len(nt_img), "secret": secret}


def test_search() -> list[str]:
    print("partitions: a quick search finds file systems that are no longer in the table")
    image, want = build_disk()
    path = os.path.join(tempfile.mkdtemp(prefix="tizo-parts-"), "disk.img")
    with open(path, "wb") as fh:
        fh.write(image)
    failures: list[str] = []
    reader = open_source(path)
    found = Searcher(reader).quick()
    reader.close()
    by = {(f.filesystem, f.start): f for f in found}
    failures += _check("FAT32 found", ("fat32", want["fat32"]) in by, str(sorted(by)))
    failures += _check("exFAT found", ("exfat", want["exfat"]) in by)
    nt = by.get(("ntfs", want["ntfs"]))
    failures += _check("formatted-over NTFS found through its backup boot sector",
                       nt is not None and nt.boot_patch > 0, nt.found_by if nt else "missing")
    ext = by.get(("ext4", want["ext4"]))
    failures += _check("ext4 placed from a backup superblock", ext is not None
                       and ext.size == 65536 * 4096 and ext.label == "rootfs", ext.found_by if ext else "missing")
    failures += _check("nothing invented", len(found) == 4, f"{len(found)} found")

    if nt is not None:
        drive = Drive(id="lost-ntfs", kind="partition", path=path, offset=nt.start, size=nt.size,
                      label="", letter="", filesystem="ntfs", free=0, disk=-1, disk_name="", bus="",
                      media="", removable=False, system=False, lost=True, boot_patch=nt.boot_patch)
        job = ScanJob(drive, QUICK).start()
        job.wait(60)
        names = {it.candidate.name: it for it in job.items}
        it = names.get("before the format.png")
        failures += _check("undo format: live files of the old volume listed too",
                           "still there when formatted.txt" in names, str(sorted(names)))
        failures += _check("undo format: files from before the format, by name",
                           job.filesystem == "ntfs" and it is not None
                           and job.data(it).read_all() == want["secret"],
                           f"fs={job.filesystem} names={sorted(names)[:4]} {job.problems}")
        job.close()

    reader = open_source(path)
    thorough = Searcher(reader).thorough()
    reader.close()
    failures += _check("thorough search agrees", {(f.filesystem, f.start) for f in thorough} == set(by),
                       str(sorted((f.filesystem, f.start) for f in thorough)))
    return failures


def main() -> int:
    failures = test_search()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all partition tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
