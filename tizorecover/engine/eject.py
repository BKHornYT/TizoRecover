"""Safely removing a USB drive ("Eject"), from inside the app.

Windows: the disk's device node is found from its instance id, then we walk up
to the USB device that carries it (a UASP drive hangs off a SCSI adapter first)
and ask Plug and Play to eject that, exactly like the tray icon does. When
Windows refuses, the veto says why ("a program is using it") and that is what
the user is told, not a bare error number. Linux: ``udisksctl`` unmounts every
partition and powers the drive off.

Callers must close their own handles to the disk first: an open handle is
itself a reason for Windows to refuse.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys

CR_SUCCESS = 0
VETO_TEXT = {   # PNP_VETO_TYPE
    0: "Windows could not say why",
    1: "an old-style driver is using it",                   # LegacyDevice
    2: "a program is still closing files on it",            # PendingClose
    3: "a program is using the drive",                      # WindowsApp
    4: "a Windows service is using the drive",              # WindowsService
    5: "a program has a file on it open",                   # OutstandingOpen
    6: "the device does not allow it",                      # Device
    7: "its driver does not allow it",                      # Driver
    8: "it is not a removable device",                      # IllegalDeviceRequest
    9: "there is not enough power to do it safely",         # InsufficientPower
    10: "Windows needs it (a page file or the system is on it)",  # NonDisableable
    11: "an old-style driver is using it",                  # LegacyDriver
    12: "TizoRecover lacks the rights (run as administrator)",    # InsufficientRights
    13: "it is already gone",                               # AlreadyRemoved
}


class EjectError(Exception):
    """Ejecting did not work; the message is for the user."""


def _instance_id_from_disk_path(path: str) -> str:
    r"""``\\?\usbstor#disk&ven_x#serial&0#{guid}`` -> ``USBSTOR\DISK&VEN_X\SERIAL&0``."""
    p = path
    if p.startswith("\\\\?\\"):
        p = p[4:]
    if "#{" in p:
        p = p[:p.index("#{")]
    return p.replace("#", "\\").upper()


def _disk_path(disk: int) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-Disk -Number {int(disk)} | Select-Object Path, BusType, IsSystem, IsBoot | ConvertTo-Json -Compress)"],
        capture_output=True, text=True, timeout=30, creationflags=flags).stdout.strip()
    if not out:
        raise EjectError("That drive is not there any more. It may already be unplugged.")
    info = json.loads(out)
    if info.get("IsSystem") or info.get("IsBoot"):
        raise EjectError("That is the disk Windows runs from; it cannot be ejected.")
    return str(info.get("Path") or "")


def _windows_eject(disk: int) -> str:
    cfg = ctypes.WinDLL("cfgmgr32")
    devinst = ctypes.c_uint32()
    instance = _instance_id_from_disk_path(_disk_path(disk))
    if cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), ctypes.c_wchar_p(instance), 0) != CR_SUCCESS:
        raise EjectError("Windows could not find the drive's device. Unplug it when its light stops blinking.")

    def device_id(node: int) -> str:
        buf = ctypes.create_unicode_buffer(512)
        if cfg.CM_Get_Device_IDW(node, buf, 512, 0) != CR_SUCCESS:
            return ""
        return buf.value.upper()

    # Walk up to the USB device itself (disk -> [SCSI adapter for UASP] -> USB\VID_...).
    target = devinst.value
    node = devinst.value
    for _ in range(4):
        parent = ctypes.c_uint32()
        if cfg.CM_Get_Parent(ctypes.byref(parent), node, 0) != CR_SUCCESS:
            break
        node = parent.value
        did = device_id(node)
        if did.startswith("USB\\VID_"):
            target = node
            break
        if did.startswith(("USB\\ROOT", "PCI\\", "ACPI\\")):
            break

    veto = ctypes.c_int(0)
    name = ctypes.create_unicode_buffer(260)
    rc = cfg.CM_Request_Device_EjectW(target, ctypes.byref(veto), name, 260, 0)
    if rc == CR_SUCCESS and veto.value == 0:
        return "Ejected. You can unplug it now."
    if veto.value == 13:
        return "It is already gone. You can unplug it."
    why = VETO_TEXT.get(veto.value, f"Windows said no (code {rc}/{veto.value})")
    who = name.value.strip()
    hint = " Close Explorer windows and programs showing files from it, then try again."
    if who and not who.upper().startswith(("USB", "USBSTOR", "STORAGE", "SCSI", "\\")):
        raise EjectError(f"Could not eject: {why} ({who}).{hint}")
    raise EjectError(f"Could not eject: {why}.{hint}")


def _linux_eject(device: str) -> str:
    if not device.startswith("/dev/"):
        raise EjectError("Unknown drive.")
    base = os.path.basename(device)
    parts = [f"/dev/{e}" for e in sorted(os.listdir(f"/sys/block/{base}")) if e.startswith(base)] \
        if os.path.isdir(f"/sys/block/{base}") else []
    for part in parts or [device]:
        subprocess.run(["udisksctl", "unmount", "-b", part, "--no-user-interaction"],
                       capture_output=True, text=True, timeout=60)
    r = subprocess.run(["udisksctl", "power-off", "-b", device, "--no-user-interaction"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise EjectError(f"Could not eject: {(r.stderr or r.stdout).strip() or 'udisksctl failed'}")
    return "Ejected. You can unplug it now."


def eject(disk: int | str) -> str:
    """Eject a disk (Windows: its number; Linux: ``/dev/sdX``). Returns the message for the user."""
    if sys.platform == "win32":
        return _windows_eject(int(disk))
    return _linux_eject(str(disk))
