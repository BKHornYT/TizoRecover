"""Carving tests: hide real files in junk and require them back intact."""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.blockdev import FileBlockReader
from tizorecover.engine.carver import carve_range, name_candidate
from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.results import Verdict
from tests import samples

JUNK = bytes(range(256)) * 40


def _build_disk(payloads: list[tuple[str, bytes]], seed: int = 7) -> tuple[bytes, dict[str, int]]:
    rng = random.Random(seed)
    out = bytearray()
    offsets: dict[str, int] = {}
    for name, data in payloads:
        out += JUNK[: rng.randrange(64, 4096)]
        offsets[name] = len(out)
        out += data
    out += JUNK[: rng.randrange(64, 4096)]
    return bytes(out), offsets


def _carve(image: bytes, chunk: int = 4096):
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        reader = FileBlockReader(path, "test")
        try:
            src = ByteSourceView(reader)
            return list(carve_range(src, "test", chunk=chunk)), src
        finally:
            reader.close()
    finally:
        os.unlink(path)


def _slice(image: bytes, offset: int, size: int) -> bytes:
    return image[offset:offset + size]


def test_each_format_roundtrip():
    print("carve: every sample format recovers byte-identical")
    failures = []
    for name, builder in samples.ALL_BUILDERS.items():
        data = builder()
        image, offsets = _build_disk([(name, data)])
        candidates, _ = _carve(image)
        want = offsets[name]
        hits = [c for c in candidates if c.data_offset == want]
        if not hits:
            print(f"  FAIL {name}: not found at {want:#x} (size {len(data)})")
            failures.append(name)
            continue
        best = max(hits, key=lambda c: c.confidence)
        recovered = _slice(image, best.data_offset, best.size)
        ok = best.size == len(data) and recovered == data
        print(
            f"  {'ok  ' if ok else 'FAIL'} {name:6s} at {want:#x} "
            f"size={best.size}/{len(data)} {best.verdict.value} conf={best.confidence:.2f}"
        )
        if not ok:
            print(f"       reasons: {best.reasons}")
            failures.append(name)
    return failures


def test_many_together():
    print("carve: a mixed disk recovers every planted file")
    payloads = [(n, b()) for n, b in samples.ALL_BUILDERS.items()]
    image, offsets = _build_disk(payloads, seed=11)
    candidates, src = _carve(image, chunk=8192)
    found = {c.data_offset for c in candidates}
    failures = []
    for name, data in payloads:
        if offsets[name] in found:
            print(f"  ok   {name}")
        else:
            print(f"  FAIL {name} missing")
            failures.append(name)
    print(f"  ({len(candidates)} candidates total from {len(image):,} bytes)")
    return failures


def test_truncated_is_partial():
    print("carve: truncated PNG is reported partial, never valid")
    data = samples.make_png()
    cut = data[: len(data) // 2]
    image, offsets = _build_disk([("png", cut)])
    candidates, _ = _carve(image)
    hits = [c for c in candidates if c.data_offset == offsets["png"]]
    if not hits:
        return ["truncated png not found at all"]
    best = max(hits, key=lambda c: c.confidence)
    ok = best.verdict in (Verdict.PARTIAL, Verdict.SUSPECT) and best.verdict is not Verdict.VALID
    print(
        f"  {'ok  ' if ok else 'FAIL'} verdict={best.verdict.value} size={best.size} "
        f"of {len(cut)} planted bytes, reasons={best.reasons}"
    )
    return [] if ok else ["truncated png mislabelled as complete"]


def test_naming():
    print("carve: unnamed candidates get readable names")
    data = samples.make_png()
    image, offsets = _build_disk([("png", data)])
    candidates, _ = _carve(image)
    hits = [c for c in candidates if c.data_offset == offsets["png"]]
    if not hits:
        return ["no candidate to name"]
    cand = name_candidate(max(hits, key=lambda c: c.confidence))
    ok = cand.name.endswith(".png") and cand.name.startswith("recovered_")
    print(f"  {'ok  ' if ok else 'FAIL'} {cand.name}")
    return [] if ok else ["naming failed"]


def test_junk_produces_no_valid_files():
    print("carve: random junk yields no VALID verdicts")
    rng = random.Random(99)
    image = bytes(rng.randrange(256) for _ in range(400_000))
    candidates, _ = _carve(image)
    valid = [c for c in candidates if c.verdict is Verdict.VALID]
    print(f"  {'ok  ' if not valid else 'FAIL'} {len(candidates)} candidates, {len(valid)} VALID")
    for c in valid[:5]:
        print(f"       false positive: {c.describe()}")
    return [] if not valid else [f"{len(valid)} false positives"]


def _overclaiming_exe(claim: int) -> bytes:
    """A PE whose one section says it is ``claim`` bytes long: a carved leftover that claims too much."""
    import struct
    pe = bytearray(0x200)
    pe[0:2] = b"MZ"
    struct.pack_into("<I", pe, 0x3C, 0x40)
    pe[0x40:0x44] = b"PE\x00\x00"
    coff = 0x44
    struct.pack_into("<HH", pe, coff, 0x14C, 1)              # machine, one section
    struct.pack_into("<H", pe, coff + 16, 0xE0)              # optional header size
    opt = coff + 20
    struct.pack_into("<H", pe, opt, 0x10B)
    struct.pack_into("<I", pe, opt + 60, 0x200)              # SizeOfHeaders
    sec = opt + 0xE0
    struct.pack_into("<II", pe, sec + 16, claim, 0x200)      # SizeOfRawData, PointerToRawData
    return bytes(pe)


def test_cluster_start_inside_claim():
    print("a file at a cluster start inside bytes an earlier carved file claims")
    rng = random.Random(4)
    image = bytearray(_overclaiming_exe(40000)) + rng.randbytes(8192 - 0x200)   # the exe "runs" to ~40 KB
    png_at = len(image)                                        # 8192: a cluster start (4 KiB clusters)
    png = samples.make_png()
    image += png + rng.randbytes(40000)
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        reader = FileBlockReader(path, "test")
        try:
            src = ByteSourceView(reader)
            plain = [(c.data_offset, c.ext) for c in carve_range(src, "t")]
            aligned = [(c.data_offset, c.ext, c.size) for c in carve_range(src, "t", align=(4096, 0))]
        finally:
            reader.close()
    finally:
        os.unlink(path)
    fails = []
    if (png_at, "png") in plain:
        fails.append("without a cluster layout the claimed bytes should be skipped (PhotoRec's rule)")
    if (png_at, "png", len(png)) not in aligned:
        fails.append(f"png at the cluster start not found inside the claim: {aligned}")
    print("   ", "ok" if not fails else fails)
    return fails


def main() -> int:
    failures: list[str] = []
    for test in (
        test_each_format_roundtrip,
        test_many_together,
        test_truncated_is_partial,
        test_naming,
        test_junk_produces_no_valid_files,
        test_cluster_start_inside_claim,
    ):
        failures.extend(test())
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all carving tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
