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

CHUNK = 4 << 20
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
                "admin": is_admin()}

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


def _open(k, path: str, write: bool) -> int:
    access = GENERIC_READ | (GENERIC_WRITE if write else 0)
    h = k.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
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


class EraseJob:
    """Overwrites one disk on a worker thread."""

    def __init__(self, plan: Plan, method: str = "zeros", filesystem: str | None = "exfat",
                 label: str = "USB") -> None:
        self.plan = plan
        self.method = method if method in ("zeros", "random") else "zeros"
        self.filesystem = filesystem if filesystem in ("exfat", "ntfs", "fat32") else None
        self.label = "".join(c for c in (label or "USB") if c.isalnum() or c in " -_")[:11] or "USB"
        self.state = "starting"
        self.stage = "preparing"
        self.done = 0
        self.total = 0
        self.passes = 2 if self.method == "random" else 1
        self.pass_no = 0
        self.started = time.time()
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
        elapsed = time.time() - self.started
        overall_total = self.total * self.passes
        overall_done = self.total * max(0, self.pass_no - 1) + self.done if self.pass_no else 0
        eta = None
        if self.state == "running" and overall_done and elapsed > 3:
            eta = (overall_total - overall_done) / (overall_done / elapsed)
        return {"state": self.state, "stage": self.stage, "done": overall_done,
                "total": overall_total, "pass": self.pass_no, "passes": self.passes,
                "elapsed": round(elapsed), "eta": None if eta is None else round(eta),
                "error": self.error, "result": self.result, "disk": self.plan.disk,
                "disk_name": self.plan.disk_name}

    def _run(self) -> None:
        self.state = "running"
        k = _kernel32()
        locks = []
        disk = None
        try:
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
            disk = _open(k, f"\\\\.\\PhysicalDrive{self.plan.disk}", write=True)
            length = int.from_bytes(_ioctl(k, disk, IOCTL_DISK_GET_LENGTH_INFO, 8)[:8], "little")
            if length <= 0:
                raise EraseError("Could not read the disk's size.")
            self.total = length
            for self.pass_no in range(1, self.passes + 1):
                fill_random = self.method == "random" and self.pass_no == 1
                self.stage = "random data" if fill_random else "zeros"
                self._overwrite(k, disk, length, fill_random)
                if self._stop.is_set():
                    break
            if self._stop.is_set():
                self.state = "stopped"
                self.stage = "stopped"
                self.result = ("Stopped part-way. The drive is partly erased and has no usable "
                               "filesystem; run the erase again or format it.")
                return
            self.stage = "verifying"
            bad = self._verify(k, disk, length)
            if bad:
                raise EraseError(f"{bad} of {VERIFY_SAMPLES} sampled sectors were not zero after "
                                 f"erasing. The drive may be failing or write-protected.")
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
            self.result = (f"Every byte of {self.plan.disk_name} was overwritten"
                           f"{' with random data, then zeros' if self.passes == 2 else ' with zeros'}, "
                           f"and a sample read back clean."
                           + (f" It now has one empty {self.filesystem.upper()} partition."
                              if self.filesystem else " It has no partition now."))
        except (EraseError, OSError) as exc:
            self.state = "failed"
            self.stage = "failed"
            self.error = str(exc)
        finally:
            if disk is not None:
                k.CloseHandle(disk)
            for h in locks:
                k.CloseHandle(h)

    def _overwrite(self, k, disk, length: int, fill_random: bool) -> None:
        pos = ctypes.c_longlong(0)
        k.SetFilePointerEx(disk, 0, ctypes.byref(pos), 0)
        zeros = ctypes.create_string_buffer(CHUNK)
        written = wintypes.DWORD(0)
        self.done = 0
        while self.done < length and not self._stop.is_set():
            n = min(CHUNK, length - self.done)
            buf = ctypes.create_string_buffer(os.urandom(n), n) if fill_random else zeros
            if not k.WriteFile(disk, buf, n, ctypes.byref(written), None) or written.value != n:
                raise EraseError(f"Writing failed at byte {self.done:,} "
                                 f"(error {ctypes.get_last_error()}). The drive may be "
                                 f"write-protected or failing.")
            self.done += n

    def _verify(self, k, disk, length: int) -> int:
        sector = 512
        sectors = length // sector
        picks = {0, sectors - 1} | {random.randrange(sectors) for _ in range(VERIFY_SAMPLES - 2)}
        buf = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD(0)
        bad = 0
        for s in sorted(picks):
            offset = min(s * sector, length - 4096) // 4096 * 4096
            k.SetFilePointerEx(disk, offset, None, 0)
            if not k.ReadFile(disk, buf, 4096, ctypes.byref(got), None):
                bad += 1
                continue
            if buf.raw[:got.value].count(0) != got.value:
                bad += 1
        return bad

    def _format(self) -> None:
        fs = {"exfat": "exFAT", "ntfs": "NTFS", "fat32": "FAT32"}[self.filesystem]
        script = (
            f"$ErrorActionPreference='Stop'; Update-HostStorageCache; "
            f"$d = Get-Disk -Number {self.plan.disk}; "
            f"if ($d.PartitionStyle -eq 'RAW') {{ Initialize-Disk -Number {self.plan.disk} -PartitionStyle MBR }}; "
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
