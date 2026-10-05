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


def main() -> int:
    failures = test_each_new_format() + test_all_together()
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all new format tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
