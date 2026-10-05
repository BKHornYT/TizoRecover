"""D5 formats: every new type comes back byte-identical and under its real name."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.samples_extra import EXTRA_BUILDERS
from tests.samples_more import MORE_BUILDERS

MORE_BUILDERS = {**MORE_BUILDERS, **EXTRA_BUILDERS}
from tests.test_carver import _build_disk, _carve


def test_each_new_format() -> list[str]:
    print("formats: new types recover exactly and are named by their contents")
    failures = []
    for label, builder in MORE_BUILDERS.items():
        data, want_ext = builder()
        image, offsets = _build_disk([(label, data)])
        candidates, _ = _carve(image, chunk=8192)
        hits = [c for c in candidates if c.data_offset == offsets[label]]
        if not hits:
            print(f"  FAIL {label:5s} not found ({len(data)} bytes)")
            failures.append(label)
            continue
        c = hits[0]
        same = c.size == len(data) and image[c.data_offset:c.data_offset + c.size] == data
        named = c.ext == want_ext
        ok = same and named
        print(f"  {'ok  ' if ok else 'FAIL'} {label:5s} size {c.size}/{len(data)} as .{c.ext} {c.verdict.value}"
              + ("" if ok else f"  {c.reasons}"))
        if not ok:
            failures.append(label)
    return failures


def test_all_together() -> list[str]:
    print("formats: all new types on one disk, none lost behind another")
    payloads = [(label, builder()[0]) for label, builder in MORE_BUILDERS.items()]
    image, offsets = _build_disk(payloads, seed=5)
    candidates, _ = _carve(image, chunk=16384)
    found = {c.data_offset for c in candidates}
    missing = [label for label, _ in payloads if offsets[label] not in found]
    print(f"  {'ok  ' if not missing else 'FAIL'} {len(payloads) - len(missing)}/{len(payloads)} found"
          + (f", missing {missing}" if missing else ""))
    return missing


def test_minecraft_chunk_is_not_a_video() -> list[str]:
    """A Minecraft region chunk of 435 bytes starts 00 00 01 B3 (its length), then 02 78 9C (zlib). On the owner's
    stick 51 of those sat at cluster starts and Disk Drill listed them as .m1v videos."""
    import random
    import zlib
    rng = random.Random(8)
    chunks = b""
    for _ in range(6):
        body = b"\x02" + zlib.compress(rng.randbytes(430))
        chunk = len(body).to_bytes(4, "big")
        chunk = b"\x00\x00\x01\xb3" + body[:431]
        chunks += chunk + bytes(4096 - len(chunk))
    found, _src = _carve(chunks, chunk=4096)
    videos = [c for c in found if c.ext in ("m1v", "m2v")]
    print("minecraft chunks:", "ok" if not videos else f"{len(videos)} taken for video")
    return [] if not videos else ["minecraft chunk carved as video"]


def main() -> int:
    failures = test_each_new_format() + test_all_together() + test_minecraft_chunk_is_not_a_video()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all new format tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
