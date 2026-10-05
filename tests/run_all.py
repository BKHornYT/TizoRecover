"""Run every test suite; exit non-zero if any fails. Used by CI and the build."""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_carver.py", "test_ntfs.py", "test_fat.py", "test_e2e.py", "test_session.py",
          "test_tzscan.py", "test_exfat.py", "test_partitions.py",
          "test_formats_more.py", "test_ext4.py", "test_robust.py", "test_fixdrive.py", "test_naming.py", "test_i30.py",
          "test_magicsearch.py", "test_qformat.py"]


def main() -> int:
    failed = []
    for suite in SUITES:
        print(f"=== {suite}")
        rc = subprocess.run([sys.executable, os.path.join(HERE, suite)],
                            cwd=os.path.dirname(HERE)).returncode
        if rc != 0:
            failed.append(suite)
    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"all {len(SUITES)} suites passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
