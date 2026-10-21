"""Entry point for `python -m terraproof.provenance`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from terraproof.checks.base import FAIL, PASS, WARN
from terraproof.provenance._core import verify_manifest, write_manifest

EXIT_USAGE = 1
EXIT_PASS = 0
EXIT_WARN = 2
EXIT_FAIL = 3
EXIT_STATUS = {PASS: EXIT_PASS, WARN: EXIT_WARN, FAIL: EXIT_FAIL}


class _Parser(argparse.ArgumentParser):
    """Exit with status 1 on usage errors."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m terraproof.provenance",
        description="Write and verify deterministic run manifests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_Parser, metavar="COMMAND")

    write_parser = subparsers.add_parser("write", help="write a run manifest")
    write_parser.add_argument("--inputs", nargs="+", required=True, metavar="PATH", help="input file paths")
    write_parser.add_argument("--outputs", nargs="+", required=True, metavar="PATH", help="output file paths")
    write_parser.add_argument("--params", metavar="JSON", help="JSON file with run parameters")
    write_parser.add_argument("--stac", nargs="+", default=[], metavar="ITEM.json", help="local STAC Item files")
    write_parser.add_argument("--root", metavar="DIR", help="root directory for relative paths (default: parent of --out)")
    write_parser.add_argument("--out", required=True, metavar="FILE", help="manifest output path")

    verify_parser = subparsers.add_parser("verify", help="verify a run manifest")
    verify_parser.add_argument("manifest", metavar="MANIFEST", help="manifest file to verify")
    verify_parser.add_argument("--root", metavar="DIR", help="root directory for resolving recorded paths")
    verify_parser.add_argument("--format", choices=["json", "text"], default="text", help="output format")
    return parser


def _cmd_write(args: argparse.Namespace) -> int:
    parameters = {}
    if args.params:
        with open(args.params, encoding="utf-8") as handle:
            parameters = json.load(handle)
        if not isinstance(parameters, dict):
            raise ValueError("--params JSON must be an object")

    manifest = write_manifest(
        inputs=args.inputs,
        outputs=args.outputs,
        parameters=parameters,
        stac_items=args.stac,
        root=args.root,
        manifest_path=args.out,
        command_line=sys.argv,
    )

    text = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    check = verify_manifest(args.manifest, root=args.root)

    if args.format == "json":
        output = json.dumps(check.to_dict(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    else:
        status_label = check.status.upper()
        parts = [f"provenance.reproducible: {status_label}"]
        if check.evidence.get("missing"):
            parts.append(f"missing: {', '.join(check.evidence['missing'])}")
        if check.evidence.get("changed"):
            parts.append(f"changed: {', '.join(check.evidence['changed'])}")
        if check.evidence.get("drifted"):
            tools = ", ".join(sorted(check.evidence["drifted"]))
            parts.append(f"version drift: {tools}")
        if check.evidence.get("expected_core_sha256"):
            parts.append("core does not match recorded hash (edited or corrupted)")
        parts.append(check.message)
        output = "\n".join(parts) + "\n"

    sys.stdout.write(output)
    return EXIT_STATUS[check.status]


def _run(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    args = _build_parser().parse_args(argv)
    try:
        if args.command == "write":
            return _cmd_write(args)
        return _cmd_verify(args)
    except Exception as exc:  # CLI boundary: input problems are usage-level failures
        print(f"terraproof.provenance: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(_run())
