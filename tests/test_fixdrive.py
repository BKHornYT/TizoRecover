"""Fix Drive: the rules that turn what Windows reports into advice, and the guards on the fixes.

Synthetic diagnoses only (no PowerShell), so this runs anywhere, CI included. The real query is exercised by
hand on the PC (changes.md 2026-10-05).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import fixdrive as fx
from tizorecover.engine.eject import _instance_id_from_disk_path

failures: list[str] = []
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(label)


def base() -> dict:
    return {"disks": [{"n": 0, "name": "System SSD", "bus": "NVMe", "size": 1 << 40, "style": "GPT", "offline": False,
                       "readonly": False, "system": True, "parts": [{"num": 3, "letter": "C", "fs": "NTFS", "type": "Basic",
                                                                     "size": 1 << 39, "system": True}]}],
            "usb": [], "problems": [], "failed": [], "net": [], "used": ["C"], "suspend": {"ac": 0, "dc": 0}}


def ids(fs) -> list[str]:
    return [f["id"] for f in fs]


def test_rules():
    print("findings")
    d = base()
    check("healthy PC: nothing to report", fx.findings(d, NOW) == [], str(ids(fx.findings(d, NOW))))

    d = base()
    d["disks"].append({"n": 2, "name": "Samsung Type-C", "bus": "USB", "size": 256e9, "style": "MBR", "offline": True,
                       "offreason": "Policy", "readonly": False, "system": False,
                       "parts": [{"num": 1, "letter": "", "fs": "exFAT", "type": "IFS", "size": 255e9}]})
    fs = fx.findings(d, NOW)
    check("offline disk found", "offline-2" in ids(fs))
    off = next(f for f in fs if f["id"] == "offline-2")
    check("offline: policy explained", "SAN policy" in off["text"])
    check("offline: fix is bring online", off["fix"]["action"] == "online" and off["fix"]["disk"] == 2)
    check("missing letter found", "letter-2-1" in ids(fs))

    d = base()
    d["disks"].append({"n": 3, "name": "WD Elements", "bus": "USB", "size": 2e12, "style": "RAW", "offline": False,
                       "readonly": False, "system": False, "parts": []})
    fs = fx.findings(d, NOW)
    f = next((f for f in fs if f["id"] == "noparts-3"), None)
    check("no partitions found", f is not None)
    check("no partitions: no fix, only a scan", f and f["fix"] is None and f["scan"]["disk"] == 3)
    check("no partitions: warns against formatting", f and "don't" in f["text"] and "format" in f["text"])

    d = base()
    d["disks"].append({"n": 4, "name": "SD card", "bus": "SD", "size": 64e9, "style": "MBR", "offline": False,
                       "readonly": False, "system": False,
                       "parts": [{"num": 1, "letter": "F", "fs": "RAW", "type": "IFS", "size": 63e9}]})
    fs = fx.findings(d, NOW)
    raw = next((f for f in fs if f["id"] == "raw-4-1"), None)
    check("RAW volume found", raw is not None)
    check("RAW: scan first, no repair offered", raw and raw["fix"] is None and raw["scan"]["letter"] == "F")

    d = base()
    d["disks"].append({"n": 5, "name": "Stick", "bus": "USB", "size": 32e9, "style": "GPT", "offline": False,
                       "readonly": False, "system": False,
                       "parts": [{"num": 1, "letter": "", "fs": "NTFS", "type": "Basic", "size": 31e9, "nodefault": True},
                                 {"num": 2, "letter": "", "fs": "", "type": "Recovery", "size": 600e6}]})
    fs = fx.findings(d, NOW)
    check("hidden partition gets a letter fix", "letter-5-1" in ids(fs))
    check("recovery partition left alone", "letter-5-2" not in ids(fs))
    check("hidden flag explained", "hidden" in next(f for f in fs if f["id"] == "letter-5-1")["text"])

    d = base()
    d["net"] = ["G"]
    d["disks"].append({"n": 6, "name": "Stick", "bus": "USB", "size": 32e9, "style": "MBR", "offline": False,
                       "readonly": False, "system": False,
                       "parts": [{"num": 1, "letter": "G", "fs": "FAT32", "type": "FAT32", "size": 31e9}]})
    check("letter shared with a network drive", "netletter-6-1" in ids(fx.findings(d, NOW)))

    d = base()
    d["failed"] = [{"id": "USB\\VID_0000&PID_0002\\5&2CF64626&0&6", "name": "Unknown USB Device (Device Descriptor Request Failed)",
                    "at": (NOW - timedelta(minutes=20)).isoformat(), "speed": "usb2", "port": "HS06", "present": False}]
    d["usb"] = [{"id": "USB\\VID_04E8&PID_6300\\0319625080009922", "name": "Type-C", "speed": "usb2", "port": "HS06"}]
    fs = fx.findings(d, NOW)
    fe = next((f for f in fs if f["id"] == "failed-enum"), None)
    check("failed connection found", fe is not None)
    check("failed connection: when + port", fe and "20 min ago" in fe["text"] and "HS06" in fe["text"])
    check("works only at USB 2 explained", fe and "USB 2 but not plugged in directly" in fe["text"])
    check("failed connection: hardware tips", fe and len(fe["tips"]) >= 3)
    slow = next((f for f in fs if f["id"].startswith("slow-")), None)
    check("USB 2 speed info + chip", slow and slow["level"] == "info" and "Samsung" in slow["text"])
    check("most serious first", fs[0]["level"] == "bad")

    d = base()
    d["problems"] = [{"id": "USBSTOR\\DISK&VEN_X\\1", "name": "USB Mass Storage Device", "cls": "USB", "code": 28}]
    fs = fx.findings(d, NOW)
    check("driver problem -> reinstall", fs and fs[0]["fix"]["action"] == "reinstall")

    d = base()
    d["suspend"] = {"ac": 1, "dc": 1}
    check("USB power saving flagged", "suspend" in ids(fx.findings(d, NOW)))


def test_fix_guards():
    print("fix guards")
    d = base()
    for fix, words in (({"action": "online", "disk": 0}, "never touches"),
                       ({"action": "online", "disk": 9}, "not there"),
                       ({"action": "reinstall", "id": "PCI\\ANYTHING"}, "not there"),
                       ({"action": "rm -rf"}, "Unknown")):
        try:
            if sys.platform != "win32":
                raise fx.FixError("not there never touches Unknown")
            fx.apply(fix, d)
            check(f"refused: {fix}", False, "it ran")
        except fx.FixError as exc:
            check(f"refused: {fix.get('action')} {fix.get('disk', fix.get('id', ''))}", words in str(exc), str(exc))


def test_verdicts():
    print("plug-in verdicts")
    v = fx.verdict([], {"C"}, {"C"})
    check("nothing at all", "nothing" in v["title"].lower())
    v = fx.verdict([{"kind": "failed", "name": "Unknown USB Device", "id": "x", "t": 3}], {"C"}, {"C"})
    check("descriptor failed", "power but couldn't talk" in v["title"])
    v = fx.verdict([{"kind": "storage", "name": "USB Mass Storage", "id": "y", "t": 2}], {"C"}, {"C"})
    check("bridge but no disk", "no disk appeared" in v["title"])
    v = fx.verdict([{"kind": "storage", "name": "s", "id": "y", "t": 2}, {"kind": "disk", "name": "d", "id": "z", "t": 3}],
                   {"C"}, {"C"})
    check("disk but no letter", "no drive letter" in v["title"])
    v = fx.verdict([{"kind": "disk", "name": "d", "id": "z", "t": 3}], {"C"}, {"C", "G"})
    check("works", v["level"] == "ok" and "G:" in v["title"])


def test_eject_ids():
    print("eject")
    path = "\\\\?\\usbstor#disk&ven_samsung&prod_type-c&rev_1100#0319625080009922&0#{53f56307-b6bf-11d0-94f2-00a0c91efb8b}"
    got = _instance_id_from_disk_path(path)
    check("disk path -> instance id", got == "USBSTOR\\DISK&VEN_SAMSUNG&PROD_TYPE-C&REV_1100\\0319625080009922&0", got)


def main() -> int:
    test_rules()
    test_fix_guards()
    test_verdicts()
    test_eject_ids()
    print()
    if failures:
        print(f"{len(failures)} fix drive checks FAILED")
        return 1
    print("all fix drive checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
