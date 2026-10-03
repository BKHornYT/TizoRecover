"""Erasing a whole removable drive so nothing on it can be recovered.

This is the one place TizoRecover writes to a drive, so it is fenced in on
purpose: only removable disks, never the disk Windows or TizoRecover itself
runs from, administrator only, and only after a confirmation that was
prepared at least a few seconds earlier, names the exact disk, and still
matches that disk (same number, model and size) when it is carried out.

Every byte of the disk is overwritten (zeros, or random data first and
zeros after), then a few sectors are read back to check, and optionally a
fresh partition and filesystem are created so the drive is usable again.

Flash media (USB sticks, SD cards, SSDs) keep spare blocks the controller
hides from the computer; no software can reach those, so an overwrite is
very thorough but not a guarantee against a lab. That is said in the UI.
"""

from __future__ import annotations

import ctypes
import os
import random
import secrets
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from tizorecover.engine.drives import Drive, is_admin, list_drives

MIN_WAIT = 5.0
TOKEN_LIFETIME = 300.0
VERIFY_SAMPLES = 64

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
INVALID_HANDLE = ctypes.c_void_p(-1).value


class EraseError(Exception):
    """A refusal or failure meant to be shown to the user as is."""


@dataclass
class Plan:
    """A prepared erase: what was shown to the user and when."""

    token: str
    disk: int
    disk_name: str
    size: int
    phrase: str
    created: float


def _self_disks(drives: list[Drive]) -> set[int]:
    """Disks holding this program, its Python, or Windows."""
    paths = {sys.executable, os.path.abspath(__file__), os.environ.get("SystemRoot", "C:\\Windows"),
             os.environ.get("TEMP", "")}
    letters = {os.path.splitdrive(p)[0][:1].upper() for p in paths if p}
    return {d.disk for d in drives if d.letter and d.letter.upper() in letters}


def disk_summary(disk: int, drives: list[Drive]) -> dict:
    parts = [d for d in drives if d.disk == disk]
    if not parts:
        raise EraseError("That disk is not connected any more.")
    letters = sorted({d.letter for d in parts if d.letter})
    return {"disk": disk, "disk_name": parts[0].disk_name, "bus": parts[0].bus,
            "removable": all(d.removable for d in parts), "system": any(d.system for d in parts),
            "letters": letters, "size": sum(d.size for d in parts),
            "volumes": [{"letter": d.letter, "label": d.label, "filesystem": d.filesystem,
                         "size": d.size} for d in parts]}


def check_allowed(disk: int, drives: list[Drive]) -> dict:
    """The disk's summary, or EraseError explaining why it may not be erased."""
    info = disk_summary(disk, drives)
    if sys.platform != "win32":
        raise EraseError("Erasing is only available on Windows for now.")
    if info["system"]:
        raise EraseError("This is the disk Windows runs from. TizoRecover will never erase it.")
    if disk in _self_disks(drives):
        raise EraseError("TizoRecover itself is running from this disk, so it cannot erase it.")
    if not info["removable"]:
        raise EraseError("Only removable drives (USB sticks, memory cards, USB disks) can be "
                         "erased here. Internal drives are left alone on purpose.")
    return info


def phrase_for(info: dict) -> str:
    if info["letters"]:
        return "ERASE " + " ".join(f"{l}:" for l in info["letters"])
    return f"ERASE DISK {info['disk']}"


class Planner:
    """Hands out erase confirmations and checks them on the way back."""

    def __init__(self) -> None:
        self.plans: dict[str, Plan] = {}

    def prepare(self, disk: int) -> dict:
        drives = list_drives()
        info = check_allowed(disk, drives)
        plan = Plan(secrets.token_urlsafe(16), disk, info["disk_name"], info["size"],
                    phrase_for(info), time.time())
        self.plans = {k: p for k, p in self.plans.items()
                      if time.time() - p.created < TOKEN_LIFETIME}
        self.plans[plan.token] = plan
        return {**info, "token": plan.token, "phrase": plan.phrase, "wait": MIN_WAIT,
                "admin": is_admin(), "estimates": estimate(info["size"])}

    def confirm(self, token: str, typed: str, understood: bool) -> Plan:
        plan = self.plans.pop(token, None)
        if plan is None:
            raise EraseError("This confirmation has expired. Open the erase dialog again.")
        age = time.time() - plan.created
        if age > TOKEN_LIFETIME:
            raise EraseError("This confirmation has expired. Open the erase dialog again.")
        if age < MIN_WAIT:
            raise EraseError("Too quick. Read the warning first.")
        if not understood:
            raise EraseError("Tick the box to confirm you understand this cannot be undone.")
        if typed.strip().upper() != plan.phrase.upper():
            raise EraseError(f"Type exactly: {plan.phrase}")
        if not is_admin():
            raise EraseError("Erasing a drive needs administrator rights. Restart TizoRecover "
                             "as administrator first.")
        info = check_allowed(plan.disk, list_drives())
        if info["disk_name"] != plan.disk_name or info["size"] != plan.size:
            raise EraseError("The drive changed since the dialog opened (unplugged or swapped?). "
                             "Nothing was erased.")
        return plan


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.ReadFile.argtypes = k.WriteFile.argtypes
    k.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                   ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _open(k, path: str, write: bool, flags: int = 0) -> int:
    access = GENERIC_READ | (GENERIC_WRITE if write else 0)
    h = k.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
    if h in (None, INVALID_HANDLE):
        raise EraseError(f"Could not open {path} (error {ctypes.get_last_error()}).")
    return h


def _ioctl(k, h, code: int, out_size: int = 0) -> bytes:
    out = ctypes.create_string_buffer(out_size) if out_size else None
    got = wintypes.DWORD(0)
    ok = k.DeviceIoControl(h, code, None, 0, out, out_size, ctypes.byref(got), None)
    if not ok:
        raise OSError(ctypes.get_last_error(), "DeviceIoControl failed")
    return out.raw[:got.value] if out is not None else b""


METHODS = ("quick", "zeros", "random")
TYPICAL_WRITE = (15 << 20, 40 << 20)   # what USB sticks and SD cards really sustain, bytes/s
QUICK_SPAN = 64 << 20                   # zeroed at each partition start and at both disk ends
MFT_SPAN = 256 << 20                    # zeroed from the NTFS $MFT (and its mirror) onwards
BIG_CHUNK = 32 << 20
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_WRITE_THROUGH = 0x80000000


def estimate(size: int) -> dict:
    """Rough durations shown before an erase starts (seconds, low-high)."""
    slow, fast = TYPICAL_WRITE
    return {"quick": [10, 60],
            "zeros": [int(size / fast), int(size / slow)],
            "random": [int(2 * size / fast), int(2 * size / slow)]}


def _aligned(k, size: int):
    k.VirtualAlloc.restype = ctypes.c_void_p
    k.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    k.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
    ptr = k.VirtualAlloc(None, size, MEM_COMMIT_RESERVE, PAGE_READWRITE)
    if not ptr:
        raise EraseError("Out of memory for the erase buffer.")
    return ptr


def _partitions(disk: int) -> list[tuple[int, int]]:
    """``(offset, size)`` of every partition on the disk, from Windows."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        f"Get-Partition -DiskNumber {disk} | ForEach-Object {{ \"$($_.Offset) $($_.Size)\" }}"],
                       capture_output=True, text=True, timeout=60, creationflags=flags)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out.append((int(parts[0]), int(parts[1])))
    return out


class EraseJob:
    """Erases one disk on a worker thread.

    ``quick``   zeroes what makes files findable by name: the partition table (both GPT copies),
                each partition's first 64 MiB (boot sector, FAT tables, exFAT/FAT root folders)
                and the NTFS $MFT and its mirror, then formats. Seconds. File contents are still
                on the drive and a deep scan can find them; the UI says so.
    ``zeros``   overwrites every byte. Blocks that already read as zeros are skipped: flash reads
                several times faster than it writes, so empty space costs almost nothing.
    ``random``  random data over everything, then zeros (two full passes, nothing skipped).
    """

    def __init__(self, plan: Plan, method: str = "quick", filesystem: str | None = "exfat",
                 label: str = "USB") -> None:
        self.plan = plan
        self.method = method if method in METHODS else "quick"
        self.filesystem = filesystem if filesystem in ("exfat", "ntfs", "fat32") else None
        self.label = "".join(c for c in (label or "USB") if c.isalnum() or c in " -_")[:11] or "USB"
        self.state = "starting"
        self.stage = "preparing"
        self.done = 0
        self.total = 0
        self.skipped = 0
        self.passes = 2 if self.method == "random" else 1
        self.pass_no = 0
        self.started = time.time()
        self.pass_started = time.time()
        self.error = ""
        self.result = ""
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="tizo-erase", daemon=True)

    def start(self) -> "EraseJob":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        now = time.time()
        overall_total = self.total * self.passes
        overall_done = self.total * max(0, self.pass_no - 1) + self.done if self.pass_no else 0
        eta = None
        pass_elapsed = now - self.pass_started
        if self.state == "running" and self.pass_no and self.done and pass_elapsed > 3:
            rate = self.done / pass_elapsed
            if rate > 0:
                eta = (overall_total - overall_done) / rate
        return {"state": self.state, "stage": self.stage, "method": self.method,
                "done": overall_done, "total": overall_total, "skipped": self.skipped,
                "pass": self.pass_no, "passes": self.passes, "elapsed": round(now - self.started),
                "eta": None if eta is None else round(eta), "error": self.error,
                "result": self.result, "disk": self.plan.disk, "disk_name": self.plan.disk_name}

    def _run(self) -> None:
        self.state = "running"
        k = _kernel32()
        locks = []
        disk = None
        buf = zero = None
        try:
            parts = _partitions(self.plan.disk) if self.method == "quick" else []
            self.stage = "unmounting"
            for d in list_drives():
                if d.disk != self.plan.disk or d.kind != "volume":
                    continue
                try:
                    h = _open(k, d.path, write=True)
                except EraseError:
                    continue
                for _ in range(10):
                    try:
                        _ioctl(k, h, FSCTL_LOCK_VOLUME)
                        break
                    except OSError:
                        time.sleep(0.5)
                try:
                    _ioctl(k, h, FSCTL_DISMOUNT_VOLUME)
                except OSError:
                    pass
                locks.append(h)
            disk = _open(k, f"\\\\.\\PhysicalDrive{self.plan.disk}", write=True,
                         flags=FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH)
            length = int.from_bytes(_ioctl(k, disk, IOCTL_DISK_GET_LENGTH_INFO, 8)[:8], "little")
            if length <= 0:
                raise EraseError("Could not read the disk's size.")
            buf = _aligned(k, BIG_CHUNK)
            zero = _aligned(k, BIG_CHUNK)
            if self.method == "quick":
                self._quick(k, disk, length, parts, buf, zero)
            else:
                self.total = length
                for self.pass_no in range(1, self.passes + 1):
                    fill_random = self.method == "random" and self.pass_no == 1
                    self.stage = "random data" if fill_random else "zeros"
                    self.pass_started = time.time()
                    self._overwrite(k, disk, length, buf, zero, fill_random,
                                    skip_blank=self.method == "zeros")
                    if self._stop.is_set():
                        break
            if self._stop.is_set():
                self.state = "stopped"
                self.stage = "stopped"
                self.result = ("Stopped part-way. The drive is partly erased and has no usable "
                               "filesystem; run the erase again or format it.")
                return
            self.stage = "verifying"
            bad = self._verify(k, disk, length, buf, self._quick_regions(length, parts)
                               if self.method == "quick" else None)
            if bad:
                raise EraseError(f"{bad} sampled blocks were not zero after erasing. The drive "
                                 f"may be failing or write-protected.")
            try:
                _ioctl(k, disk, IOCTL_DISK_UPDATE_PROPERTIES)
            except OSError:
                pass
            k.CloseHandle(disk)
            disk = None
            for h in locks:
                k.CloseHandle(h)
            locks = []
            if self.filesystem:
                self.stage = "formatting"
                self._format()
            self.state = "done"
            self.stage = "done"
            took = round(time.time() - self.started)
            if self.method == "quick":
                what = ("Quick erase done: the partition table, boot sectors and file tables are "
                        "gone, so no names or folders can come back. File contents can still be "
                        "found by a deep scan; use a full erase to destroy those too.")
            else:
                what = (f"Every byte of {self.plan.disk_name} is now "
                        f"{'random data, then zeros' if self.passes == 2 else 'zero'}"
                        f"{f' ({self.skipped / 2**30:.1f} GB was already blank and was skipped)' if self.skipped else ''}"
                        f", and a sample read back clean.")
            fs = (f" It now has one empty {self.filesystem.upper()} partition." if self.filesystem
                  else " It has no partition now.")
            self.result = f"{what}{fs} Took {took // 60} min {took % 60} s."
        except (EraseError, OSError) as exc:
            self.state = "failed"
            self.stage = "failed"
            self.error = str(exc)
        finally:
            if disk is not None:
                k.CloseHandle(disk)
            for h in locks:
                k.CloseHandle(h)
            for p in (buf, zero):
                if p:
                    k.VirtualFree(p, 0, MEM_RELEASE)

    def _write(self, k, disk, offset: int, length: int, src) -> None:
        k.SetFilePointerEx(disk, offset, None, 0)
        written = wintypes.DWORD(0)
        if not k.WriteFile(disk, src, length, ctypes.byref(written), None) or written.value != length:
            raise EraseError(f"Writing failed at byte {offset:,} (error {ctypes.get_last_error()}). "
                             f"The drive may be write-protected or failing.")

    def _read(self, k, disk, offset: int, length: int, dst) -> bytes:
        k.SetFilePointerEx(disk, offset, None, 0)
        got = wintypes.DWORD(0)
        if not k.ReadFile(disk, dst, length, ctypes.byref(got), None):
            return b""
        return ctypes.string_at(dst, got.value)

    def _quick_regions(self, length: int, parts: list[tuple[int, int]]) -> list[tuple[int, int]]:
        regions = [(0, QUICK_SPAN), (max(0, length - QUICK_SPAN), QUICK_SPAN)]
        for offset, size in parts:
            regions.append((offset, min(QUICK_SPAN, size)))
        regions += getattr(self, "_mft_regions", [])
        out = []
        for offset, size in regions:
            start = offset // 4096 * 4096
            end = min(length, -(-(offset + size) // 4096) * 4096)
            if end > start:
                out.append((start, end - start))
        return out

    def _quick(self, k, disk, length: int, parts, buf, zero) -> None:
        self.stage = "file tables"
        self._mft_regions = []
        for offset, size in parts:
            boot = self._read(k, disk, offset, 4096, buf)
            if len(boot) >= 512 and boot[3:11] == b"NTFS    ":
                bps = int.from_bytes(boot[0x0B:0x0D], "little")
                spc = boot[0x0D]
                cluster = bps * spc
                for field in (0x30, 0x38):          # $MFT and $MFTMirr cluster numbers
                    lcn = int.from_bytes(boot[field:field + 8], "little")
                    start = offset + lcn * cluster
                    if offset < start < offset + size:
                        self._mft_regions.append((start, min(MFT_SPAN, offset + size - start)))
        regions = self._quick_regions(length, parts)
        self.total = sum(n for _o, n in regions)
        self.pass_no = 1
        self.pass_started = time.time()
        for offset, size in regions:
            pos = offset
            while pos < offset + size and not self._stop.is_set():
                n = min(BIG_CHUNK, offset + size - pos)
                self._write(k, disk, pos, n, zero)
                pos += n
                self.done += n

    def _overwrite(self, k, disk, length: int, buf, zero, fill_random: bool, skip_blank: bool) -> None:
        self.done = 0
        pos = 0
        while pos < length and not self._stop.is_set():
            n = min(BIG_CHUNK, length - pos)
            if skip_blank:
                data = self._read(k, disk, pos, n, buf)
                if len(data) == n and data.count(0) == n:
                    self.skipped += n
                    pos += n
                    self.done += n
                    continue
            if fill_random:
                ctypes.memmove(buf, os.urandom(n), n)
                self._write(k, disk, pos, n, buf)
            else:
                self._write(k, disk, pos, n, zero)
            pos += n
            self.done += n

    def _verify(self, k, disk, length: int, buf, regions=None) -> int:
        if regions:
            picks = []
            for offset, size in regions:
                picks += [offset, offset + max(0, size - 4096)]
        else:
            picks = [0, length - 4096] + [random.randrange(length // 4096) * 4096
                                          for _ in range(VERIFY_SAMPLES - 2)]
        bad = 0
        for offset in sorted(set(picks)):
            offset = max(0, min(offset, length - 4096)) // 4096 * 4096
            data = self._read(k, disk, offset, 4096, buf)
            if not data or data.count(0) != len(data):
                bad += 1
        return bad

    def _format(self) -> None:
        fs = {"exfat": "exFAT", "ntfs": "NTFS", "fat32": "FAT32"}[self.filesystem]
        script = (
            f"$ErrorActionPreference='Stop'; Update-HostStorageCache; "
            f"Update-Disk -Number {self.plan.disk}; "
            f"$d = Get-Disk -Number {self.plan.disk}; "
            f"if ($d.PartitionStyle -eq 'RAW') {{ Initialize-Disk -Number {self.plan.disk} -PartitionStyle MBR }}; "
            f"Get-Partition -DiskNumber {self.plan.disk} -ErrorAction SilentlyContinue | Remove-Partition -Confirm:$false; "
            f"$p = New-Partition -DiskNumber {self.plan.disk} -UseMaximumSize -AssignDriveLetter; "
            f"Format-Volume -Partition $p -FileSystem {fs} -NewFileSystemLabel '{self.label}' "
            f"-Confirm:$false | Out-Null; $p.DriveLetter"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=600, creationflags=flags)
        if r.returncode != 0:
            raise EraseError("The drive was erased, but formatting it failed: "
                             + (r.stderr.strip().splitlines() or ["unknown error"])[-1]
                             + " Format it in Windows (right-click it in This PC).")
