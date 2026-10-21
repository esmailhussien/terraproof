"""Entry point for `python -m terraproof.mcp`: serve the Terraproof tools over stdio."""

import sys


def _run() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    # Imported here so that `--help`-style failures and a missing extra are reported early.
    from terraproof.mcp.server import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    _run()
