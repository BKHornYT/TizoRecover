"""PyInstaller entry script.

PyInstaller runs its entry script as a bare ``__main__`` with no parent
package, so ``tizorecover/__main__.py`` cannot be the entry itself: its
absolute imports would work, but keeping the package import explicit here
means the frozen app and ``python -m tizorecover`` take the same path.
"""

import sys

from tizorecover.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
