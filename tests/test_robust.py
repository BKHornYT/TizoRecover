"""TizoRecover must not crash on broken drives.

Two kinds of broken:
- **Damaged file systems**: every test image (NTFS, FAT32, exFAT, ext4) is scanned again and again with random
  bytes flipped and sectors zeroed in its metadata. Any scan that ends in "scan failed" is a parser that let an
  exception out on bad input: the user would lose the whole scan for one bad byte.
- **Failing hardware**: a raw reader whose drive has bad sectors must skip them (zeros, counted) and keep going,
  and one whose drive disappears must say so instead of reading endless zeros.
"""

from __future__ import annotations

import errno
import gzip
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.blockdev import DeviceBlockReader, DriveGoneError
from tizorecover.engine.drives import image_drive
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tests import fsimages, samples
from tests.exfatimage import ExfatBuilder

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ROUNDS = int(os.environ.get("TIZO_FUZZ_ROUNDS", "25"))
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(f"{label} {detail}")


def images() -> dict[str, bytes]:
    out = {}
    n = fsimages.NtfsBuilder()
    n.add_live_file("keep.txt", b"still here\n" * 20)
    n.add_deleted_file("photo.png", samples.make_png())
    n.add_deleted_file("notes.txt", b"deleted notes\n" * 400)
    out["ntfs"] = n.build()
    f = fsimages.Fat32Builder()
    d = f.add_dir("Photos")
    f.add_live_file("keep.txt", b"still here", into=d)
    f.add_deleted_file("photo.png", samples.make_png(), into=d)
    f.add_deleted_file("notes.txt", b"deleted notes\n" * 400)
    out["fat32"] = f.build()
    e = ExfatBuilder()
    p = e.add_dir("Photos")
    e.add_file("keep.png", samples.make_png(), into=p)
    e.add_file("gone.png", samples.make_png(), into=p, deleted=True)
    out["exfat"] = e.build()
    with gzip.open(os.path.join(FIX, "ext4-deleted.img.gz"), "rb") as fh:
        out["ext4"] = fh.read()
    return out


def damage(data: bytes, rng: random.Random) -> bytes:
    """Flip bytes and blank sectors, mostly where the file system keeps its tables."""
    buf = bytearray(data)
    hot = min(len(buf), 4 << 20)
    for _ in range(rng.randint(1, 40)):
        pos = rng.randrange(hot) if rng.random() < 0.85 else rng.randrange(len(buf))
        buf[pos] ^= rng.randint(1, 255)
    for _ in range(rng.randint(0, 3)):
        sec = rng.randrange(hot // 512) * 512
        fill = rng.choice((b"\x00", b"\xff"))
        buf[sec:sec + 512] = fill * 512
    if rng.random() < 0.2:                       # an insane length/pointer somewhere
        pos = rng.randrange(hot - 8)
        buf[pos:pos + 8] = b"\xff\xff\xff\x7f\xff\xff\xff\x7f"
    return bytes(buf)


def scan(path: str, mode: str) -> ScanJob:
    job = ScanJob(image_drive(path), mode).start()
    job.wait(120)
    return job


def test_damaged_file_systems():
    print(f"damaged file systems ({ROUNDS} rounds each)")
    work = tempfile.mkdtemp(prefix="tizo-robust-")
    for name, data in images().items():
        rng = random.Random(f"tizo-{name}")
        crashed = []
        for r in range(ROUNDS):
            path = os.path.join(work, f"{name}-{r}.img")
            with open(path, "wb") as fh:
                fh.write(damage(data, rng))
            job = scan(path, DEEP if r % 5 == 0 else QUICK)
            bad = [p for p in job.problems if p.startswith("scan failed")]
            if job.state not in ("done", "stopped") or bad:
                crashed.append(f"round {r}: {job.state} {bad[:1]}")
            else:
                for item in job.snapshot()[:15]:          # previews read the found data too
                    try:
                        job.data(item).at(0, 4096)
                    except OSError:
                        pass
                    except Exception as exc:              # noqa: BLE001
                        crashed.append(f"round {r}: reading {item.candidate.name}: {exc!r}")
                        break
            job.close()
            os.unlink(path)
        check(f"{name}: no scan crashed", not crashed, "; ".join(crashed[:3]))


class FlakyDrive(DeviceBlockReader):
    """A drive (really an image file) with bad sectors, or one that vanishes."""

    def __init__(self, path: str, bad: list[tuple[int, int]], gone_after: int | None = None) -> None:
        super().__init__(path)
        self.bad = bad
        self.gone_after = gone_after
        self.calls = 0

    def _read_raw(self, offset: int, length: int) -> bytes:
        self.calls += 1
        if self.gone_after is not None and self.calls > self.gone_after:
            raise OSError(errno.ENODEV if os.name != "nt" else 0, "device gone")
        for a, b in self.bad:
            if offset < b and offset + length > a:
                raise OSError(errno.EIO, "I/O error (bad sector)")
        return super()._read_raw(offset, length)


def test_bad_sectors_and_vanishing_drive():
    print("failing hardware")
    data = bytes(range(256)) * (4 << 12)                # 4 MiB of a known pattern
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    fh.write(data)
    fh.close()
    bad = [(1 << 20, (1 << 20) + 4096), (3 << 20, (3 << 20) + 8192)]
    drive = FlakyDrive(fh.name, bad)
    got = drive.read(0, len(data))
    check("whole read still returns every byte", len(got) == len(data), str(len(got)))
    expect = bytearray(data)
    for a, b in bad:
        expect[a:b] = b"\x00" * (b - a)
    check("only the bad sectors read as blank", got == bytes(expect))
    check("bad bytes counted", drive.bad_bytes == 4096 + 8192, str(drive.bad_bytes))
    check("bad ranges recorded", drive.bad_ranges == bad, str(drive.bad_ranges))
    drive.close()

    if os.name == "nt":
        gone_err = OSError(0, "gone")
        gone_err.winerror = 1167                          # ERROR_DEVICE_NOT_CONNECTED
    else:
        gone_err = OSError(errno.ENODEV, "gone")

    class Gone(FlakyDrive):
        def _read_raw(self, offset, length):
            raise gone_err

    g = Gone(fh.name, [])
    try:
        g.read(0, 4096)
        check("a vanished drive is reported", False, "read returned data")
    except DriveGoneError:
        check("a vanished drive is reported", True)
    g.close()
    os.unlink(fh.name)


def main() -> int:
    test_bad_sectors_and_vanishing_drive()
    test_damaged_file_systems()
    print()
    if failures:
        print(f"{len(failures)} robustness checks FAILED")
        return 1
    print("all robustness checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
