"""Parallel magic search: must give exactly what one finditer gives, and carve the same files."""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TIZO_CARVE_WORKERS", "4")

from tizorecover.engine import magicsearch
from tizorecover.engine.blockdev import FileBlockReader
from tizorecover.engine.carver import carve_range
from tizorecover.engine.formats import BY_MAGIC, ByteSourceView
from tests import samples

MB = 1 << 20


def _seeded_buffer(size: int, seed: int) -> bytes:
    """Random bytes with magics planted everywhere, densest around the slice seams."""
    rng = random.Random(seed)
    buf = bytearray(rng.randbytes(size))
    magics = sorted(BY_MAGIC, key=len)
    workers = magicsearch._worker_count()
    step = -(-size // workers)
    seams = [step * k for k in range(1, workers)]
    for _ in range(20000):
        m = rng.choice(magics)
        at = rng.randrange(0, size - len(m))
        buf[at:at + len(m)] = m
    for seam in seams:                       # every position a magic can straddle a seam from
        for back in range(1, magicsearch.MAX_MAGIC + 2):
            m = rng.choice(magics)
            at = seam - back
            buf[at:at + len(m)] = m
            # a second magic starting inside the first one
            m2 = rng.choice(magics)
            at2 = at + rng.randrange(0, len(m))
            buf[at2:at2 + len(m2)] = m2
    return bytes(buf)


def test_same_hits_as_serial() -> list[str]:
    fails = []
    for seed in range(6):
        size = (1 + seed) * MB + seed * 777
        buf = _seeded_buffer(size, seed)
        got = magicsearch.find_magics(buf)
        want = magicsearch.search_serial(buf)
        if got != want:
            diff = next(i for i, (g, w) in enumerate(zip(got, want)) if g != w) if got and want else 0
            fails.append(f"seed {seed}: {len(got)} vs {len(want)} hits, first difference at #{diff}")
    if magicsearch._helpers is None or magicsearch._helpers.broken:
        fails.append("helpers did not run (parallel path untested)")
    print("same hits as serial:", "ok" if not fails else fails)
    return fails


def test_carve_same_files() -> list[str]:
    rng = random.Random(3)
    image = bytearray()
    for builder in samples.ALL_BUILDERS.values():
        data = builder()
        image += rng.randbytes(rng.randrange(0, 3 * MB))
        image += data
    image += rng.randbytes(MB)
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        def run():
            reader = FileBlockReader(path, "test")
            try:
                return [(c.data_offset, c.size, c.ext) for c in carve_range(ByteSourceView(reader), "t")]
            finally:
                reader.close()
        parallel = run()
        saved, magicsearch.PARALLEL_MIN = magicsearch.PARALLEL_MIN, 1 << 62
        try:
            serial = run()
        finally:
            magicsearch.PARALLEL_MIN = saved
    finally:
        os.unlink(path)
    fails = [] if parallel == serial and parallel else [f"parallel {len(parallel)} vs serial {len(serial)} files"]
    print(f"carve same files: {len(parallel)} files,", "ok" if not fails else fails)
    return fails


def test_speed() -> list[str]:
    buf = random.Random(9).randbytes(64 * MB)
    magicsearch.find_magics(buf[:8 * MB])                # warm up the helpers
    t = time.perf_counter()
    for i in range(0, len(buf), 8 * MB):
        magicsearch.find_magics(buf[i:i + 8 * MB])
    par = len(buf) / MB / (time.perf_counter() - t)
    t = time.perf_counter()
    for i in range(0, len(buf), 8 * MB):
        magicsearch.search_serial(buf[i:i + 8 * MB])
    ser = len(buf) / MB / (time.perf_counter() - t)
    print(f"speed on random data: parallel {par:.0f} MB/s, one core {ser:.0f} MB/s")
    if (os.cpu_count() or 1) < 6:                       # small CI runners: report, don't judge
        return []
    return [] if par > ser else [f"parallel ({par:.0f}) not faster than one core ({ser:.0f})"]


def main() -> int:
    failures: list[str] = []
    for test in (test_same_hits_as_serial, test_carve_same_files, test_speed):
        failures.extend(test())
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all magic search tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
