"""Explicit model download and cache inspection: python -m terraproof.router --download-model.

Keep this module tiny and optional: it imports the semantic extra only when invoked.
No routing entrypoint lives here; use ``terraproof route`` for routing.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m terraproof.router", description=__doc__)
    parser.add_argument("--download-model", action="store_true",
                        help="Download the pinned semantic model into the user cache (never the repo).")
    args = parser.parse_args(argv)
    if not args.download_model:
        parser.print_usage(sys.stderr)
        return 1
    try:
        from .semantic import cache_dir, model_path
        path = model_path(download=True)
    except Exception as exc:
        print(f"terraproof.router: error: {exc}", file=sys.stderr)
        return 1
    print(f"model ready at {path.as_posix()}")
    print(f"cache root: {cache_dir().as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
