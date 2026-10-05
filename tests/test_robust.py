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

    # A damaged area where every read times out (a sick drive): it must be skipped in a few tries,
    # not retried sector by sector (8 MB / 4 KB = 2048 reads of 15 s each = 8.5 hours).
    big = bytes(range(256)) * (4 << 15)                 # 32 MiB
    with open(fh.name, "wb") as out:
        out.write(big)

    class Slow(FlakyDrive):
        slow_calls = 0

        def _read_raw(self, offset, length):
            self.calls += 1
            if offset < (12 << 20) and offset + length > (4 << 20):
                self.slow_calls += 1
                raise OSError(1460, "the drive did not answer within 15 s")
            return DeviceBlockReader._read_raw(self, offset, length)

    slow = Slow(fh.name, [])
    got = b"".join(slow.read(o, 8 << 20) for o in range(0, 32 << 20, 8 << 20))
    check("slow area: every byte still returned", len(got) == len(big), str(len(got)))
    check("slow area: few slow reads (each would cost 15 s)", slow.slow_calls <= 12, f"{slow.slow_calls} slow reads")
    check("slow area: counted as unreadable", slow.bad_bytes >= (8 << 20) - (128 << 10), str(slow.bad_bytes))
    check("slow area: data before it intact", got[:4 << 20] == big[:4 << 20])
    check("slow area: data after it intact", got[16 << 20:] == big[16 << 20:])
    slow.close()

    stopper = Slow(fh.name, [])
    stopper.interrupt()
    stopper.calls = 0
    stopper.read(0, 8 << 20)
    check("Stop: no more retries once interrupted", stopper.calls <= 2, f"{stopper.calls} reads")
    stopper.resume()
    check("after Stop, reads work again", stopper.read(0, 4096) == big[:4096])
    stopper.close()

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


def test_stop_stops():
    print("stop really stops")
    import time
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    rng = random.Random(3)
    fh.write(bytes(rng.getrandbits(8) for _ in range(1 << 20)) * 768)    # 768 MiB of noise: a long deep scan
    fh.close()
    job = ScanJob(image_drive(fh.name), DEEP).start()
    t = time.time()                      # stop once the deep stage is underway (it runs at 200+ MB/s now)
    while time.time() - t < 10 and not (job.progress.stage == "deep" and job.progress.done > 0):
        time.sleep(0.02)
    t = time.time()
    job.stop()
    job.wait(10)
    took = time.time() - t
    check("deep scan stops within 2 s", job.state == "stopped" and took < 2, f"{job.state} after {took:.2f} s")
    check("a stopped scan can still read its drive", job.src is not None and len(job.src.at(0, 512)) == 512)
    job.close()
    os.unlink(fh.name)


def test_disconnect_pauses_and_continues():
    print("a drive that disconnects pauses the scan, which carries on when it is back")
    import time
    from tizorecover.engine import session as session_mod
    from tests.test_session import noisy_png
    raw = bytearray(24 << 20)
    for k in range(12):                                   # pictures spread over the whole image
        pic = noisy_png(80 + k * 7, 60, k)
        raw[(k * 2 << 20) + 4096:(k * 2 << 20) + 4096 + len(pic)] = pic
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    fh.write(bytes(raw))
    fh.close()

    ref = ScanJob(image_drive(fh.name), DEEP).start()
    ref.wait(60)
    want = sorted((it.candidate.data_offset, it.candidate.size) for it in ref.snapshot())
    ref.close()

    real_open = session_mod.open_drive
    state = {"opens": 0}

    class Dropping:
        """The first time the drive is opened, it vanishes after a few reads (unplugged)."""
        def __init__(self, inner):
            self.inner, self.size, self.label, self.reads = inner, inner.size, inner.label, 0

        def read(self, offset, length):
            self.reads += 1
            if self.reads > 6:
                raise DriveGoneError(1167, "device not connected", fh.name)
            return self.inner.read(offset, length)

        def read_at(self, offset, length):
            data = self.read(offset, min(length, self.size - offset)) if offset < self.size else b""
            return data + b"\x00" * (min(length, max(0, self.size - offset)) - len(data))

        def close(self):
            self.inner.close()

    def flaky_open(drive):
        state["opens"] += 1
        r = real_open(drive)
        return Dropping(r) if state["opens"] == 1 else r

    session_mod.open_drive = flaky_open
    try:
        job = ScanJob(image_drive(fh.name), DEEP).start()
        paused_seen = False
        for _ in range(200):
            if job.state == "paused":
                paused_seen = True
            if job.state in ("done", "failed", "stopped"):
                break
            time.sleep(0.05)
        job.wait(60)
    finally:
        session_mod.open_drive = real_open
    got = sorted((it.candidate.data_offset, it.candidate.size) for it in job.snapshot())
    check("it paused instead of failing", paused_seen and job.state == "done", f"paused={paused_seen} end={job.state}")
    check("reopened by itself when the drive was back", state["opens"] >= 2, str(state["opens"]))
    check("same files as a scan without the disconnect", got == want, f"{len(got)} vs {len(want)}")
    job.close()

    # Stop while paused ends the scan as stopped
    state["opens"] = 0
    gone = {"on": True}

    def never_back(drive):
        state["opens"] += 1
        if state["opens"] == 1:
            return Dropping(real_open(drive))
        raise OSError(2, "not there")

    session_mod.open_drive = never_back
    try:
        job = ScanJob(image_drive(fh.name), DEEP).start()
        for _ in range(100):
            if job.state == "paused":
                break
            time.sleep(0.05)
        t = time.time()
        job.stop()
        job.wait(10)
    finally:
        session_mod.open_drive = real_open
    check("Stop while paused stops at once", job.state == "stopped" and time.time() - t < 2, f"{job.state}")
    job.close()
    os.unlink(fh.name)


def main() -> int:
    test_disconnect_pauses_and_continues()
    test_stop_stops()
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
