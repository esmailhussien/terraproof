"""Entry point for `python -m terraproof`."""

import sys

from terraproof.cli import main


def _run() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    sys.exit(main())


if __name__ == "__main__":
    _run()
