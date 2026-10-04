"""Listing the drives a user can scan.

The user picks a drive, not a folder: deleted files are not in any folder any
more, they are in the volume's free space. On Windows the list comes from the
Storage cmdlets in one PowerShell call (they already know bus type, media
type and which partition carries which volume, which raw IOCTLs would have to
piece together). A partition with no volume behind it -- a Linux partition,
or one Windows cannot read -- is still listed, read through the physical disk
at the partition's offset.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass

_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$disks = @(Get-Disk | ForEach-Object { [pscustomobject]@{
  n = $_.Number; name = $_.FriendlyName; bus = "$($_.BusType)"; size = $_.Size;
  boot = $_.IsBoot; system = $_.IsSystem; style = "$($_.PartitionStyle)" } })
$phys = @(Get-PhysicalDisk | ForEach-Object { [pscustomobject]@{ id = "$($_.DeviceId)"; media = "$($_.MediaType)" } })
$parts = @(Get-Partition | ForEach-Object {
  $v = $null; $v = $_ | Get-Volume
  [pscustomobject]@{ disk = $_.DiskNumber; num = $_.PartitionNumber; offset = $_.Offset; size = $_.Size;
    type = "$($_.Type)"; gpt = "$($_.GptType)"; letter = "$($_.DriveLetter)".Trim([char]0);
    fs = "$($v.FileSystem)"; label = "$($v.FileSystemLabel)"; free = [int64]$v.SizeRemaining;
    vsize = [int64]$v.Size; vpath = "$($v.Path)" } })
@{ disks = $disks; phys = $phys; parts = $parts } | ConvertTo-Json -Depth 4 -Compress
"""

HIDDEN_TYPES = {"Reserved"}
MIN_PARTITION = 32 << 20
LINUX_GUIDS = {"{0fc63daf-8483-4772-8e79-3d69d8477de4}": "Linux"}


@dataclass
class Drive:
    """One thing the user can scan: a volume, a bare partition or an image file."""

    id: str
    kind: str
    path: str
    offset: int
    size: int
    label: str
    letter: str
    filesystem: str
    free: int
    disk: int
    disk_name: str
    bus: str
    media: str
    removable: bool
    system: bool
    partition: int = 0
    disk_size: int = 0
    disk_offset: int = 0      # where the partition starts on its disk
    lost: bool = False        # found by the partition search, not in the table
    found_by: str = ""
    parent: str = ""          # the disk number or image id a lost partition was found on
    boot_patch: int = -1      # surviving boot copy to read in place of the first sectors
    patch_len: int = 512

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def title(self) -> str:
        if self.letter:
            return f"{self.letter}:  {self.label or self.disk_name}"
        return self.label or self.disk_name or self.path


def is_admin() -> bool:
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _volume_device(vpath: str) -> str:
    r"""``\\?\Volume{guid}\`` -> ``\\.\Volume{guid}`` for raw reads."""
    if vpath.startswith("\\\\?\\"):
        vpath = "\\\\.\\" + vpath[4:]
    return vpath.rstrip("\\")


def _windows_drives() -> list[Drive]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS],
        capture_output=True, text=True, timeout=60, creationflags=flags,
    ).stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    disks = {d["n"]: d for d in _as_list(data.get("disks"))}
    media = {str(p["id"]): p["media"] for p in _as_list(data.get("phys"))}
    drives: list[Drive] = []
    for p in _as_list(data.get("parts")):
        disk = disks.get(p["disk"], {})
        if p["type"] in HIDDEN_TYPES or (p["size"] or 0) < MIN_PARTITION:
            continue
        bus = disk.get("bus", "")
        letter = p.get("letter") or ""
        fs = p.get("fs") or LINUX_GUIDS.get((p.get("gpt") or "").lower(), "")
        if p.get("vpath") and p.get("fs"):
            kind, path, offset = "volume", (f"\\\\.\\{letter}:" if letter else _volume_device(p["vpath"])), 0
            size = p.get("vsize") or p["size"]
        else:
            kind, path, offset, size = "partition", f"\\\\.\\PhysicalDrive{p['disk']}", p["offset"], p["size"]
        drives.append(Drive(
            id=f"d{p['disk']}p{p['num']}", kind=kind, path=path, offset=offset, size=size,
            label=p.get("label") or "", letter=letter, filesystem=fs or "unknown",
            free=p.get("free") or 0, disk=p["disk"], disk_name=disk.get("name", ""),
            bus=bus, media=media.get(str(p["disk"]), ""),
            removable=bus in ("USB", "SD", "MMC"), system=bool(disk.get("system") or disk.get("boot")),
            partition=p["num"], disk_size=int(disk.get("size") or 0),
            disk_offset=int(p.get("offset") or 0),
        ))
    drives.sort(key=lambda d: (not d.removable, d.system, d.disk, d.partition))
    return drives


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _linux_drives() -> list[Drive]:
    drives: list[Drive] = []
    base = "/sys/class/block"
    if not os.path.isdir(base):
        return drives
    mounts: dict[str, str] = {}
    try:
        with open("/proc/mounts", encoding="utf-8") as fh:
            for line in fh:
                dev, mnt, fs = line.split()[:3]
                mounts[dev] = fs
    except OSError:
        pass
    for name in sorted(os.listdir(base)):
        if name.startswith(("loop", "ram", "zram", "dm-")):
            continue
        part = os.path.exists(os.path.join(base, name, "partition"))
        parent = os.path.basename(os.path.dirname(os.path.realpath(os.path.join(base, name)))) if part else name
        try:
            sectors = int(open(os.path.join(base, name, "size")).read())
            removable = open(os.path.join(base, parent, "removable")).read().strip() == "1"
            rotational = open(os.path.join(base, parent, "queue", "rotational")).read().strip() == "1"
        except (OSError, ValueError):
            continue
        has_parts = any(e.startswith(name) and e != name for e in os.listdir(base)) and not part
        if has_parts or sectors * 512 < MIN_PARTITION:
            continue
        dev = f"/dev/{name}"
        drives.append(Drive(
            id=name, kind="volume", path=dev, offset=0, size=sectors * 512, label="",
            letter="", filesystem=mounts.get(dev, "unknown"), free=0, disk=0,
            disk_name=parent, bus="USB" if removable else "", media="HDD" if rotational else "SSD",
            removable=removable, system=False, disk_size=sectors * 512,
        ))
    drives.sort(key=lambda d: (not d.removable, d.path))
    return drives


def list_drives() -> list[Drive]:
    """Every scannable drive, removable ones first."""
    if sys.platform == "win32":
        return _windows_drives()
    return _linux_drives()


def image_drive(path: str) -> Drive:
    """A disk image file, treated like any other drive."""
    size = os.path.getsize(path)
    return Drive(id="img:" + os.path.abspath(path), kind="image", path=os.path.abspath(path),
                 offset=0, size=size, label=os.path.basename(path), letter="",
                 filesystem="unknown", free=0, disk=-1, disk_name="Disk image", bus="File",
                 media="", removable=False, system=False, disk_size=size)


def disk_of_path(path: str, drives: list[Drive]) -> int | None:
    """Physical disk number holding ``path``, for the never-write-to-source check."""
    letter = os.path.splitdrive(os.path.abspath(path))[0][:1].upper()
    for d in drives:
        if d.letter and d.letter.upper() == letter:
            return d.disk
    return None
