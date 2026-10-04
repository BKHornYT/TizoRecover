"""Carving benchmark on real files: speed, and how many come back exactly.

Not a test suite (it needs real media and takes a while). It copies local
files into one blob, back to back with 4 KiB alignment and random or zero
gaps like free space between deleted files, remembers where each starts, then
carves the blob and scores: found at the right offset, and the exact size.

    python tests/bench_carve.py build corpus.bin [--mb 600]   # from ~/Videos, ~/Downloads, Windows media, DLLs
    python tests/bench_carve.py run corpus.bin

Reference (2026-10-04, 600 MB, 117 files): before D2 50 MB/s and 14 exact
with 22 false hits; after D2 ~200 MB/s, 116 exact (one MP4 is 10 bytes
short of trailing padding), 0 false hits. The blob is in the OS cache, so
this measures CPU; a USB stick is limited by the stick (~80 MB/s on the
Kingston).
"""

from __future__ import annotations

import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATTERNS = ["Videos/*.mp4", "Downloads/*.mp4", "Music/*.mp4", "Pictures/Screenshots/*.png", "Downloads/*.zip",
            "Downloads/*.pdf", "Downloads/*.jpg", "Downloads/*.mp3", "Music/*.mp3"]
ALIAS = {"dll": "exe", "jpeg": "jpg"}


def build(out: str, budget_mb: int = 600) -> None:
    home = os.path.expanduser("~")
    files: list[str] = []
    for pattern in PATTERNS:
        files += sorted(glob.glob(os.path.join(home, pattern)))[:12]
    files += glob.glob(r"C:\Windows\Web\Wallpaper\*\*.jpg") + glob.glob(r"C:\Windows\Media\*.wav")[:30]
    files += sorted(glob.glob(r"C:\Windows\System32\*.dll"))[:60]
    rng = random.Random(1)
    rng.shuffle(files)
    budget, total, manifest = budget_mb << 20, 0, []
    with open(out, "wb") as fh:
        for path in files:
            try:
                size = os.path.getsize(path)
                if size > 120 << 20 or total + size > budget:
                    continue
                with open(path, "rb") as src:
                    data = src.read()
            except OSError:
                continue
            manifest.append([total, len(data), os.path.splitext(path)[1].lower()[1:]])
            fh.write(data)
            total += len(data)
            pad = (-total) % 4096 + 4096 * rng.randint(0, 3)
            fh.write(rng.randbytes(pad) if rng.random() < 0.3 else b"\0" * pad)
            total += pad
    with open(out + ".json", "w") as fh:
        json.dump(manifest, fh)
    print(f"{total >> 20} MB, {len(manifest)} files -> {out}")


def run(path: str) -> None:
    from tizorecover.engine.blockdev import open_source
    from tizorecover.engine.carver import carve_range
    from tizorecover.engine.formats import ByteSourceView

    with open(path + ".json") as fh:
        truth = json.load(fh)
    src = ByteSourceView(open_source(path))
    started = time.time()
    found = list(carve_range(src, "bench"))
    took = time.time() - started
    exact = {(c.data_offset, c.size) for c in found}
    starts = {c.data_offset for c in found}
    by: dict[str, list[int]] = {}
    for off, size, ext in truth:
        row = by.setdefault(ALIAS.get(ext, ext), [0, 0, 0])
        row[0] += 1
        row[1] += off in starts
        row[2] += (off, size) in exact
    print(f"{src.size / 1e6 / took:.1f} MB/s ({took:.1f}s), {len(found)} candidates")
    print("type  files  start  exact")
    for ext, (n, s, e) in sorted(by.items()):
        print(f"  {ext:4s} {n:5d} {s:6d} {e:6d}")
    true_starts = {o for o, _s, _e in truth}
    extra: dict[str, int] = {}
    for c in found:
        if c.data_offset not in true_starts:
            extra[c.ext] = extra.get(c.ext, 0) + 1
    print(f"exact {sum(r[2] for r in by.values())} of {len(truth)}; false or embedded hits: {extra or 'none'}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        mb = int(sys.argv[sys.argv.index("--mb") + 1]) if "--mb" in sys.argv else 600
        build(sys.argv[2], mb)
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    else:
        print(__doc__)
