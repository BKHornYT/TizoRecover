"""``python -m tizorecover``: the window with no arguments, the CLI with any."""

from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args == ["--browser"]:
        from tizorecover.app.elevate import ensure_admin
        if not ensure_admin():
            return 0
        from tizorecover.app.main import run
        return run(browser=bool(args))
    from tizorecover.cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
