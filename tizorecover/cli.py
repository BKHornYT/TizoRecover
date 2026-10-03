"""TizoRecover from a terminal: list drives, scan one, save what it finds."""

from __future__ import annotations

import argparse
import os
import sys
import time

from tizorecover import APP_NAME, __version__
from tizorecover.engine import drives as drives_mod
from tizorecover.engine.results import human_size
from tizorecover.engine.session import DEEP, QUICK, ScanJob
from tizorecover.engine.writer import save_items


def _pick_drive(name: str) -> drives_mod.Drive | None:
    if os.path.isfile(name):
        return drives_mod.image_drive(name)
    wanted = name.rstrip(":\\/").upper()
    for d in drives_mod.list_drives():
        if wanted in (d.letter.upper(), d.id.upper(), d.path.upper()):
            return d
    return None


def _cmd_drives(_args) -> int:
    rows = drives_mod.list_drives()
    if not rows:
        print("No drives found.")
        return 1
    for d in rows:
        tags = [t for t, on in (("removable", d.removable), ("system", d.system),
                                (d.media, d.media in ("SSD", "HDD"))) if on]
        print(f"{d.id:8s} {d.letter + ':' if d.letter else '  '}  {human_size(d.size):>10s}  "
              f"{d.filesystem:8s} {d.disk_name[:28]:28s} {d.label[:20]:20s} {', '.join(tags)}")
    if not drives_mod.is_admin():
        print("\nNot running as administrator: USB sticks and memory cards usually still work; "
              "internal drives need an administrator prompt.")
    return 0


def _cmd_scan(args) -> int:
    drive = _pick_drive(args.drive)
    if drive is None:
        print(f"No drive or image called {args.drive!r}. Try: tizorecover drives")
        return 2
    mode = DEEP if args.deep else QUICK
    print(f"{APP_NAME} {__version__}: {mode} scan of {drive.title} ({drive.path})")
    job = ScanJob(drive, mode).start()
    last = 0.0
    try:
        while job.thread.is_alive():
            time.sleep(0.5)
            if time.time() - last >= 2 or not job.thread.is_alive():
                last = time.time()
                s = job.status()
                p = s["progress"]
                total = f" of {human_size(p['total'])}" if p["total"] else ""
                eta = f", {p['eta']}s left" if p["eta"] is not None else ""
                print(f"\r  {p['stage']:8s} {human_size(p['done'])}{total}  found {s['found']}"
                      f"  {p['elapsed']:.0f}s{eta}      ", end="", flush=True)
    except KeyboardInterrupt:
        job.stop()
        job.wait()
    print()
    s = job.status()
    for problem in s["problems"]:
        print(f"  note: {problem}")
    items = job.snapshot()
    c = s["counts"]
    print(f"Found {len(items)} file(s): {c.get('good', 0)} good, {c.get('partial', 0)} partial, "
          f"{c.get('overwritten', 0)} overwritten. Filesystem: {s['filesystem']}.")
    if args.list or not args.output:
        for it in items:
            d = it.to_dict()
            print(f"  [{d['status']:11s}] {human_size(d['size']):>10s}  "
                  f"{d['path'] or d['name']}  ({d['method']})")
    if args.output:
        wanted = [it for it in items if args.all or it.status != "overwritten"]
        dest_disk = drives_mod.disk_of_path(args.output, drives_mod.list_drives())
        if drive.kind != "image" and dest_disk is not None and dest_disk == drive.disk:
            print("Refusing to save onto the drive being recovered: pick another drive.")
            job.close()
            return 3
        results = save_items(wanted, job.data, args.output)
        ok = sum(1 for r in results if r[2])
        print(f"Saved {ok} of {len(results)} file(s) to {args.output}")
    job.close()
    return 0 if s["state"] in ("done", "stopped") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tizorecover",
                                     description=f"{APP_NAME}: find and recover deleted files.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("drives", help="list drives that can be scanned")
    scan = sub.add_parser("scan", help="scan a drive (E:, d2p1) or a disk image file")
    scan.add_argument("drive")
    scan.add_argument("--deep", action="store_true", help="also search free space by file content")
    scan.add_argument("-o", "--output", help="save found files to this folder (on another drive)")
    scan.add_argument("--all", action="store_true", help="also save files marked overwritten")
    scan.add_argument("--list", action="store_true", help="list every file found")
    args = parser.parse_args(argv)
    if args.cmd == "drives":
        return _cmd_drives(args)
    if args.cmd == "scan":
        return _cmd_scan(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
