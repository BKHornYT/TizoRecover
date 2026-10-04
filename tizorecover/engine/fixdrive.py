"""Fix Drive: why doesn't my drive show up, and what can be done about it.

A drive can get stuck at any layer between the plug and a drive letter, and
each layer has its own cure:

1. nothing on USB at all ..................... cable, port, power (hardware advice)
2. "Device Descriptor Request Failed" ........ powered but not talking: usually the USB 3 link
3. a USB / storage device with a problem code  driver: reinstall it
4. the disk is offline / read-only ............ bring it online
5. the disk has no partitions ................. NEVER initialise or format: scan / find lost partitions
6. a partition without a drive letter ......... assign one (clear the hidden flag first)
7. a RAW (unreadable) file system ............. recover first; repair only afterwards
plus Windows' USB power saving, which drops flaky drives.

``diagnose()`` gathers what Windows knows in one PowerShell call, ``findings()``
(pure, tested) turns it into plain-language cards, ``apply()`` runs one fix --
each one only on an id that came out of the last diagnosis, never on free text
-- and ``Watch`` follows a plug-in live. Nothing here writes to a drive's data
area: no initialise, no format, no chkdsk.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

USB_SUSPEND = ("2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226")
RECENT_DAYS = 14
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Bridge chips (the converter inside an enclosure / adapter), by USB vendor id.
BRIDGES = {
    "152D": "JMicron", "174C": "ASMedia", "0BDA": "Realtek", "2109": "VIA Labs", "05E3": "Genesys Logic",
    "1F75": "Innostor", "13FD": "Initio", "0080": "Unbranded (cheap clone)", "067B": "Prolific",
    "04E8": "Samsung", "0781": "SanDisk", "0951": "Kingston", "1058": "Western Digital", "0BC2": "Seagate",
}

_DIAG_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$since = (Get-Date).AddDays(-%(days)d)
function Speed($p) { $p = ($p -join ' '); if ($p -match 'ACPI\(SS\w*\)') { 'usb3' } elseif ($p -match 'ACPI\(HS\w*\)') { 'usb2' } else { '' } }
function Port($p) { $p = ($p -join ' '); if ($p -match '.*ACPI\(([HS]S\w*)\)') { $matches[1] } else { '' } }
$all = @(Get-PnpDevice)
$disks = @(Get-Disk | ForEach-Object {
  $d = $_
  $parts = @(Get-Partition -DiskNumber $d.Number | ForEach-Object {
    $v = $null; $v = $_ | Get-Volume
    [pscustomobject]@{ num = $_.PartitionNumber; letter = "$($_.DriveLetter)".Trim([char]0); hidden = [bool]$_.IsHidden;
      nodefault = [bool]$_.NoDefaultDriveLetter; type = "$($_.Type)"; gpt = "$($_.GptType)"; mbr = [int]$_.MbrType;
      size = [int64]$_.Size; fs = "$($v.FileSystem)"; system = [bool]($_.IsSystem -or $_.IsBoot) } })
  [pscustomobject]@{ n = $d.Number; name = "$($d.FriendlyName)"; bus = "$($d.BusType)"; size = [int64]$d.Size;
    style = "$($d.PartitionStyle)"; offline = [bool]$d.IsOffline; offreason = "$($d.OfflineReason)";
    readonly = [bool]$d.IsReadOnly; status = "$($d.OperationalStatus)"; system = [bool]($d.IsSystem -or $d.IsBoot);
    path = "$($d.Path)"; parts = $parts } })
$usb = @($all | Where-Object { $_.Present -and $_.Service -in 'USBSTOR','UASPStor' } | ForEach-Object {
  $lp = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_LocationPaths).Data
  [pscustomobject]@{ id = $_.InstanceId; name = "$((Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_BusReportedDeviceDesc).Data)";
    service = "$($_.Service)"; speed = (Speed $lp); port = (Port $lp) } })
$problems = @($all | Where-Object { $_.Present -and $_.Status -ne 'OK' -and "$($_.Class)" -in 'USB','DiskDrive','SCSIAdapter','HDC','USBDevice','WPD' } |
  ForEach-Object { [pscustomobject]@{ id = $_.InstanceId; name = "$($_.FriendlyName)"; cls = "$($_.Class)";
    code = [int](Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_ProblemCode).Data } })
$failed = @($all | Where-Object { $_.InstanceId -like 'USB\VID_0000&PID_000*' } | ForEach-Object {
  $at = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_LastArrivalDate).Data
  if ($at -and $at -gt $since) {
    $lp = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_LocationPaths).Data
    [pscustomobject]@{ id = $_.InstanceId; name = "$($_.FriendlyName)"; at = $at.ToUniversalTime().ToString('o');
      present = [bool]$_.Present; speed = (Speed $lp); port = (Port $lp) } } })
$net = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=4' | ForEach-Object { "$($_.DeviceID)".Trim(':') })
$used = @(Get-CimInstance Win32_LogicalDisk | ForEach-Object { "$($_.DeviceID)".Trim(':') })
$q = powercfg /query SCHEME_CURRENT %(sub)s %(setting)s
$idx = @($q | ForEach-Object { if ("$_" -match ':\s*0x([0-9a-fA-F]{8})\s*$') { [Convert]::ToInt32($matches[1], 16) } })
@{ disks = $disks; usb = $usb; problems = $problems; failed = $failed; net = $net; used = $used;
   suspend = @{ ac = $(if ($idx.Count -ge 2) { $idx[-2] } else { $null }); dc = $(if ($idx.Count -ge 2) { $idx[-1] } else { $null }) } } |
  ConvertTo-Json -Depth 5 -Compress
"""

_SNAP_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
@(Get-PnpDevice -PresentOnly | Where-Object { "$($_.Class)" -in 'USB','DiskDrive','SCSIAdapter','USBDevice','WPD','Volume' -or $_.InstanceId -like 'USB\*' } |
  ForEach-Object { [pscustomobject]@{ id = $_.InstanceId; name = "$($_.FriendlyName)"; cls = "$($_.Class)"; ok = ($_.Status -eq 'OK'); svc = "$($_.Service)" } }) |
  ConvertTo-Json -Compress
"""


class FixError(Exception):
    """A fix could not be applied; the message is for the user."""


def _ps(script: str, timeout: int = 90) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", script], capture_output=True, text=True, timeout=timeout, creationflags=_FLAGS)
    return (r.stdout or "").strip()


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def diagnose() -> dict:
    """Everything Windows knows about drives and USB storage right now."""
    if sys.platform != "win32":
        return {"platform": sys.platform, "disks": [], "usb": [], "problems": [], "failed": [], "net": [],
                "used": [], "suspend": {}}
    out = _ps(_DIAG_PS % {"days": RECENT_DAYS, "sub": USB_SUSPEND[0], "setting": USB_SUSPEND[1]}, timeout=120)
    data = json.loads(out) if out else {}
    for key in ("disks", "usb", "problems", "failed", "net", "used"):
        data[key] = _list(data.get(key))
    for d in data["disks"]:
        d["parts"] = _list(d.get("parts"))
    data.setdefault("suspend", {})
    data["platform"] = sys.platform
    data["at"] = time.time()
    return data


# ---------------------------------------------------------------- findings (pure)

def _vid(instance_id: str) -> str:
    m = re.search(r"VID_([0-9A-F]{4})", instance_id.upper())
    return m.group(1) if m else ""


def _gb(n: int) -> str:
    return f"{(n or 0) / 1e9:.1f} GB"


def _when(iso: str, now: datetime) -> str:
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "recently"
    delta = now - at
    if delta < timedelta(minutes=2):
        return "just now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} h ago"
    return at.astimezone().strftime("%d %b %H:%M")


DATA_GPT = "{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}"     # basic data
NO_LETTER_TYPES = {"Reserved", "System", "Recovery", "Unknown"}

HARDWARE_TIPS = [
    "Use a port on the back of the PC (front ports and cheap hubs give less power).",
    "Try a different cable, short and good quality; USB-C cables are often charge-only or USB 2 only.",
    "A 2.5\" hard disk may need more power than one port gives: use a powered hub or a Y-cable.",
    "If it only works through an adapter or at USB 2, its USB 3 connection is failing (cable, port or the "
    "drive's own connector). A USB 2 port or USB 2 cable is slower but works.",
]


def findings(data: dict, now: datetime | None = None) -> list[dict]:
    """Plain-language problems with a fix where there is a safe one. Most serious first."""
    now = now or datetime.now(timezone.utc)
    out: list[dict] = []

    def add(fid, level, title, text, fix=None, tips=None, scan=None):
        out.append({"id": fid, "level": level, "title": title, "text": text, "fix": fix,
                    "tips": tips or [], "scan": scan})

    # 2: powered but never identified itself
    failed = sorted(data.get("failed", []), key=lambda f: f.get("at", ""), reverse=True)
    if failed:
        last = failed[0]
        usb3_fail = any(f.get("speed") == "usb3" for f in failed)
        slow_ok = [u for u in data.get("usb", []) if u.get("speed") == "usb2"]
        times = "Once" if len(failed) == 1 else "Twice" if len(failed) == 2 else f"{len(failed)} times"
        text = (f"{times} in the last {RECENT_DAYS} days a USB device got "
                f"power but never told Windows what it is (\"Device Descriptor Request Failed\"), last {_when(last.get('at', ''), now)}"
                f"{' on port ' + last['port'] if last.get('port') else ''}. That is the plug, cable, power or the USB 3 "
                f"link, not the files on the drive.")
        if slow_ok:
            names = ", ".join(sorted({u.get("name") or "a USB drive" for u in slow_ok}))
            text += (f" {names} now works at USB 2 speed only: a drive that works at USB 2 but not plugged in directly "
                     f"almost always has a failing USB 3 connection.")
        add("failed-enum", "bad", "A drive failed to connect", text,
            fix={"action": "clear_failed", "label": "Clear the failed entries",
                 "why": "Removes Windows' memory of the failed attempts so the next plug-in starts clean. Safe."},
            tips=HARDWARE_TIPS if not usb3_fail else HARDWARE_TIPS[3:] + HARDWARE_TIPS[:3])

    # 3: devices with a problem code
    for p in data.get("problems", []):
        code = int(p.get("code") or 0)
        name = p.get("name") or "A USB device"
        if code == 43 or "Descriptor" in name or "Reset Failed" in name or "Set Address" in name:
            add(f"dev-{p['id']}", "bad", f"{name}",
                "Windows can see a device but it stopped answering (code 43). Usually power or the cable; "
                "a driver reinstall sometimes clears it.",
                fix={"action": "reinstall", "id": p["id"], "label": "Reinstall the driver",
                     "why": "Removes the device from Windows and searches again, like unplugging and replugging."},
                tips=HARDWARE_TIPS)
        elif code in (10, 19, 24, 28, 31, 32, 37, 38, 39, 41, 52):
            add(f"dev-{p['id']}", "bad", f"{name}: driver problem",
                f"The device is connected but its driver did not start (code {code}).",
                fix={"action": "reinstall", "id": p["id"], "label": "Reinstall the driver",
                     "why": "Removes the device from Windows and searches again; Windows installs the driver fresh."})
        elif code == 22:
            add(f"dev-{p['id']}", "warn", f"{name} is disabled", "Someone turned this device off in Device Manager.",
                fix={"action": "enable", "id": p["id"], "label": "Turn it on"})
        elif code:
            add(f"dev-{p['id']}", "warn", f"{name}: problem code {code}", "Windows reports a problem with this device.",
                fix={"action": "reinstall", "id": p["id"], "label": "Reinstall the driver"})

    nets = {x.upper() for x in data.get("net", [])}
    for d in data.get("disks", []):
        n = d.get("n")
        name = d.get("name") or f"Disk {n}"
        label = f"{name} ({_gb(d.get('size'))})"
        if d.get("system"):
            continue
        # 4
        if d.get("offline"):
            reason = d.get("offreason") or ""
            why = {"Policy": "Windows keeps new disks offline on this PC (SAN policy).",
                   "RedundantPath": "Windows thinks it is the same disk seen twice.",
                   "Collision": "it has the same ID as another disk (a clone).",
                   "CriticalWriteFailures": "it failed writes earlier; it may be failing.",
                   }.get(reason, "Windows switched it off.")
            add(f"offline-{n}", "bad", f"{label} is offline", f"It is connected but offline: {why}",
                fix={"action": "online", "disk": n, "label": "Bring it online",
                     "why": "Only switches the disk on in Windows. Nothing on it is changed (a cloned disk gets a new ID)."})
        if d.get("readonly") and not d.get("offline"):
            add(f"ro-{n}", "warn", f"{label} is read-only",
                "Windows will not write to it. That is good while you recover (TizoRecover never writes to it anyway); "
                "turn it off only when you want to use the drive normally again.",
                fix={"action": "readwrite", "disk": n, "label": "Make it writable"})
        parts = d.get("parts", [])
        # 5
        if not parts or (d.get("style") or "").upper() == "RAW":
            add(f"noparts-{n}", "bad", f"{label} has no partitions",
                "Windows sees the disk but no partitions on it, so it gets no drive letter. If Windows offers to "
                "\"initialize\" or \"format\" it: don't. That would write over what is left. Search it for lost "
                "partitions or scan the whole disk first.",
                scan={"disk": n, "kind": "disk"})
            continue
        for p in parts:
            if p.get("system") or (p.get("size") or 0) < (32 << 20):
                continue
            ptype = p.get("type") or ""
            letter = (p.get("letter") or "").upper()
            fs = (p.get("fs") or "").upper()
            plabel = f"{label}, partition {p.get('num')}"
            # 6
            if not letter and ptype not in NO_LETTER_TYPES and (fs or ptype in ("Basic", "IFS", "FAT32", "Huge", "FAT12", "FAT16")
                                                                 or (p.get("gpt") or "").lower() == DATA_GPT):
                hidden = p.get("hidden") or p.get("nodefault")
                add(f"letter-{n}-{p['num']}", "warn", f"{plabel} has no drive letter",
                    ("It is marked hidden, so Windows never gives it a letter. " if hidden else
                     "Windows did not give it a letter, so it doesn't show in Explorer. ") +
                    "Giving it one changes nothing on the drive's files.",
                    fix={"action": "letter", "disk": n, "part": p["num"], "label": "Give it a drive letter"})
            elif letter and letter in nets:
                add(f"netletter-{n}-{p['num']}", "warn", f"{plabel} shares {letter}: with a network drive",
                    f"A mapped network drive also uses {letter}:, so Explorer shows the network drive instead.",
                    fix={"action": "newletter", "disk": n, "part": p["num"], "label": "Move it to a free letter"})
            # 7
            if letter and fs in ("RAW", "") and ptype not in NO_LETTER_TYPES:
                add(f"raw-{n}-{p['num']}", "bad", f"{letter}: can't be read (RAW)",
                    "Windows can't read its file system, and will offer to format it: don't. Scan it with "
                    "TizoRecover and save your files first; repair or format only afterwards.",
                    scan={"disk": n, "part": p["num"], "letter": letter})

    # USB 2 speed info, for drives that do work
    for u in data.get("usb", []):
        if u.get("speed") == "usb2":
            vid = _vid(u.get("id", ""))
            chip = BRIDGES.get(vid, "")
            add(f"slow-{u['id']}", "info", f"{u.get('name') or 'A USB drive'} runs at USB 2 speed",
                "It works, but at USB 2 (up to ~40 MB/s): it sits on a USB 2 port or behind a USB 2 adapter or hub. "
                "Fine for recovery, just slower. If it does not show up at all on a USB 3 port, that port, the cable "
                "or the drive's USB 3 connection is the problem." + (f" Its USB chip: {chip}." if chip else ""))

    sus = data.get("suspend") or {}
    if sus.get("ac") == 1 or sus.get("dc") == 1:
        add("suspend", "warn", "USB power saving is on",
            "Windows may switch off USB ports it thinks are idle, which makes flaky drives disappear mid-scan.",
            fix={"action": "suspend_off", "label": "Turn USB power saving off",
                 "why": "Changes one power setting (USB selective suspend). It can be turned back on here."})
    elif sus.get("ac") == 0 and sus.get("dc") == 0 and _saved_suspend() is not None:
        add("suspend-undo", "info", "USB power saving is off",
            "TizoRecover turned it off earlier.", fix={"action": "suspend_restore", "label": "Turn it back on"})

    order = {"bad": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: order.get(f["level"], 3))
    return out


# ---------------------------------------------------------------- fixes

def _state_file() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "TizoRecover")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "fixdrive.json")


def _saved_suspend():
    try:
        with open(_state_file(), encoding="utf-8") as fh:
            return json.load(fh).get("suspend")
    except (OSError, ValueError):
        return None


def _q(s: str) -> str:
    """A PowerShell single-quoted literal."""
    return "'" + str(s).replace("'", "''") + "'"


def _free_letter(used: list[str]) -> str:
    taken = {x.upper() for x in used}
    for c in "DEFGHIJKLMNOPQRSTUVWXYZ":
        if c not in taken:
            return c
    raise FixError("Every drive letter is in use.")


def apply(fix: dict, data: dict) -> str:
    """Run one fix. ``data`` is the last diagnosis: ids and disk numbers must come from it."""
    if sys.platform != "win32":
        raise FixError("Fix Drive works on Windows only for now.")
    action = fix.get("action")
    disks = {d["n"]: d for d in data.get("disks", [])}
    known_ids = {p["id"] for p in data.get("problems", [])}

    def disk() -> dict:
        n = fix.get("disk")
        if n not in disks:
            raise FixError("That drive is not there any more. Check again.")
        if disks[n].get("system"):
            raise FixError("Fix Drive never touches the disk Windows runs from.")
        return disks[n]

    def part(d: dict) -> dict:
        p = next((p for p in d.get("parts", []) if p.get("num") == fix.get("part")), None)
        if p is None:
            raise FixError("That partition is not there any more. Check again.")
        return p

    if action == "online":
        d = disk()
        _run_checked(f"Set-Disk -Number {int(d['n'])} -IsOffline $false")
        return "The disk is online."
    if action == "readwrite":
        d = disk()
        _run_checked(f"Set-Disk -Number {int(d['n'])} -IsReadOnly $false")
        return "The disk is writable again."
    if action in ("letter", "newletter"):
        d = disk()
        p = part(d)
        n, num = int(d["n"]), int(p["num"])
        cmds = []
        if (d.get("style") or "").upper() == "MBR" and p.get("hidden"):
            cmds.append(f"Set-Partition -DiskNumber {n} -PartitionNumber {num} -IsHidden $false")
        if p.get("nodefault"):
            cmds.append(f"Set-Partition -DiskNumber {n} -PartitionNumber {num} -NoDefaultDriveLetter $false")
        letter = _free_letter(data.get("used", []) + data.get("net", []))
        cmds.append(f"Set-Partition -DiskNumber {n} -PartitionNumber {num} -NewDriveLetter {letter}")
        _run_checked("; ".join(cmds))
        return f"It is drive {letter}: now."
    if action == "reinstall":
        dev = fix.get("id")
        if dev not in known_ids:
            raise FixError("That device is not there any more. Check again.")
        _pnputil(["/remove-device", dev])
        _pnputil(["/scan-devices"])
        return "Done. Windows searched for the device again; give it a few seconds."
    if action == "enable":
        dev = fix.get("id")
        if dev not in known_ids:
            raise FixError("That device is not there any more. Check again.")
        _pnputil(["/enable-device", dev])
        return "Turned on."
    if action == "clear_failed":
        n = 0
        for f in data.get("failed", []):
            if not f.get("present") and str(f.get("id", "")).upper().startswith("USB\\VID_0000&PID_000"):
                _pnputil(["/remove-device", f["id"]], check=False)
                n += 1
        _pnputil(["/scan-devices"], check=False)
        return f"Cleared {n} failed entr{'y' if n == 1 else 'ies'}. Now unplug the drive and plug it in again."
    if action == "rescan":
        _pnputil(["/scan-devices"], check=False)
        _ps("Update-HostStorageCache")
        return "Windows looked for new drives again."
    if action == "suspend_off":
        sus = data.get("suspend") or {}
        try:
            with open(_state_file(), "w", encoding="utf-8") as fh:
                json.dump({"suspend": {"ac": sus.get("ac"), "dc": sus.get("dc")}}, fh)
        except OSError:
            pass
        _powercfg(0, 0)
        return "USB power saving is off."
    if action == "suspend_restore":
        old = _saved_suspend() or {"ac": 1, "dc": 1}
        _powercfg(int(old.get("ac") or 0), int(old.get("dc") or 0))
        try:
            os.unlink(_state_file())
        except OSError:
            pass
        return "USB power saving is back as it was."
    raise FixError("Unknown fix.")


def _run_checked(script: str) -> None:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "$ErrorActionPreference = 'Stop'; " + script],
                       capture_output=True, text=True, timeout=120, creationflags=_FLAGS)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise FixError(f"Windows refused: {msg[0] if msg else 'unknown error'}")


def _pnputil(args: list[str], check: bool = True) -> None:
    r = subprocess.run(["pnputil", *args], capture_output=True, text=True, timeout=120, creationflags=_FLAGS)
    if check and r.returncode not in (0, 3010):
        raise FixError(f"Windows refused: {(r.stdout or r.stderr).strip().splitlines()[-1:] or ['pnputil failed']}")


def _powercfg(ac: int, dc: int) -> None:
    sub, setting = USB_SUSPEND
    for flag, val in (("/setacvalueindex", ac), ("/setdcvalueindex", dc)):
        subprocess.run(["powercfg", flag, "SCHEME_CURRENT", sub, setting, str(val)],
                       capture_output=True, timeout=30, creationflags=_FLAGS)
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"], capture_output=True, timeout=30, creationflags=_FLAGS)


# ---------------------------------------------------------------- watch a plug-in

def snapshot() -> dict[str, dict]:
    out = _ps(_SNAP_PS, timeout=30)
    try:
        rows = _list(json.loads(out)) if out else []
    except ValueError:
        rows = []
    return {r["id"]: r for r in rows if r.get("id")}


def verdict(events: list[dict], letters_before: set[str], letters_after: set[str]) -> dict:
    """What a plug-in attempt says, from what appeared (pure, tested)."""
    new_letters = sorted(letters_after - letters_before)
    failed = [e for e in events if e["kind"] == "failed"]
    problem = [e for e in events if e["kind"] == "problem"]
    storage = [e for e in events if e["kind"] == "storage"]
    disks = [e for e in events if e["kind"] == "disk"]
    if new_letters:
        return {"level": "ok", "title": f"It works: {', '.join(l + ':' for l in new_letters)} appeared",
                "text": "The drive connected and has a letter. You can scan it now."}
    if failed:
        return {"level": "bad", "title": "The drive got power but couldn't talk to the PC",
                "text": "Windows saw something on the port but it never identified itself (Device Descriptor "
                        "Request Failed). That is the USB connection, not the files: most often a USB 3 link that "
                        "fails. Try another cable or port, or a USB 2 port or hub, which works at lower speed.",
                "tips": HARDWARE_TIPS}
    if problem:
        return {"level": "bad", "title": "The drive connected, but its driver failed",
                "text": "Use the fix below to reinstall the driver, then plug it in again.", "check": True}
    if disks:
        return {"level": "warn", "title": "The drive connected, but got no drive letter",
                "text": "Windows sees the disk. The checks below say why it has no letter and what to do.", "check": True}
    if storage:
        return {"level": "warn", "title": "The USB part connected, but no disk appeared",
                "text": "The adapter or enclosure answered but the disk behind it did not. The disk may not be "
                        "getting enough power, or the disk itself is failing (listen for clicking or beeping).",
                "tips": HARDWARE_TIPS}
    return {"level": "bad", "title": "Windows saw nothing at all",
            "text": "Nothing happened on any USB port. The plug, the cable, the port or the drive's power: try "
                    "another port (on the back), another cable, and a powered hub for a hard disk.",
            "tips": HARDWARE_TIPS}


class Watch:
    """Follows one plug-in attempt: what appears on USB, with a verdict at the end."""

    def __init__(self, seconds: int = 45) -> None:
        self.seconds = max(10, min(int(seconds), 120))
        self.state = "idle"
        self.events: list[dict] = []
        self.result: dict | None = None
        self.started = 0.0
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Watch":
        self.state = "watching"
        self.started = time.time()
        self._thread = threading.Thread(target=self._run, name="tizo-watch", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        left = max(0, int(self.started + self.seconds - time.time())) if self.state == "watching" else 0
        return {"state": self.state, "events": list(self.events), "left": left, "result": self.result,
                "error": self.error}

    def _letters(self) -> set[str]:
        if sys.platform != "win32":
            return set()
        import string
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return {c for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1}

    def _run(self) -> None:
        try:
            before = snapshot()
            letters_before = self._letters()
            seen = set(before)
            started_utc = datetime.now(timezone.utc)
            while not self._stop.is_set() and time.time() - self.started < self.seconds:
                time.sleep(1.0)
                now = snapshot()
                for dev_id, d in now.items():
                    if dev_id in seen:
                        continue
                    seen.add(dev_id)
                    up = dev_id.upper()
                    if up.startswith("USB\\VID_0000&PID_000"):
                        kind = "failed"
                    elif not d.get("ok"):
                        kind = "problem"
                    elif d.get("cls") == "DiskDrive":
                        kind = "disk"
                    elif d.get("svc") in ("USBSTOR", "UASPStor"):
                        kind = "storage"
                    else:
                        kind = "usb"
                    self.events.append({"t": round(time.time() - self.started, 1), "kind": kind,
                                        "name": d.get("name") or dev_id, "id": dev_id})
                if self._letters() - letters_before and any(e["kind"] in ("disk", "storage") for e in self.events):
                    time.sleep(1.5)
                    break
            # A failed attempt can come and go between two polls; Windows remembers it with a time.
            if sys.platform == "win32":
                for f in diagnose().get("failed", []):
                    try:
                        at = datetime.fromisoformat(f["at"].replace("Z", "+00:00"))
                    except (KeyError, ValueError):
                        continue
                    if at >= started_utc - timedelta(seconds=2) and not any(e["id"] == f["id"] for e in self.events):
                        self.events.append({"t": round((at - started_utc).total_seconds(), 1), "kind": "failed",
                                            "name": f.get("name") or "Unknown USB device", "id": f["id"]})
            self.result = verdict(self.events, letters_before, self._letters())
            self.state = "done"
        except Exception as exc:  # noqa: BLE001 - reported to the page, never a dead watch
            self.error = str(exc)
            self.state = "failed"
