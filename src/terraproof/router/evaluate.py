"""Evaluate a JSONL routing set: python -m terraproof.router.evaluate FILE."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import find_guidance
from .index import PROCESS_SKILLS, get_index


def evaluate_file(path: str | Path, top_k: int = 5) -> dict:
    """Mean per-item recall (empty expected = 1), forbidden-skill occurrences."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
        raise ValueError("top_k must be a non-negative integer")
    recalls = []
    languages: dict[str, list[float]] = {}
    failures = []
    violations = 0
    ids = set()
    allowed = set(get_index().skills) - PROCESS_SKILLS
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("item must be an object")
                if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
                    raise ValueError("id must be a unique non-empty string")
                if item.get("lang") not in ("en", "ar"):
                    raise ValueError("lang must be en or ar")
                for key in ("expected", "must_not"):
                    names = item.get(key, [] if key == "must_not" else None)
                    if not isinstance(names, list) or any(not isinstance(name, str) or name not in allowed for name in names):
                        raise ValueError(f"{key} must list registered non-process skills")
                if set(item["expected"]) & set(item.get("must_not", [])):
                    raise ValueError("expected and must_not must not overlap")
                result = find_guidance(item.get("prompt"), datasets=item.get("datasets"), top_k=top_k)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            ids.add(item["id"])
            names = [skill["name"] for skill in result["skills"]]
            expected = set(item["expected"])
            recall = len(expected.intersection(names)) / len(expected) if expected else 1.0
            forbidden = sorted(set(item.get("must_not", [])).intersection(names))
            recalls.append(recall)
            languages.setdefault(item["lang"], []).append(recall)
            violations += len(forbidden)
            if recall < 1 or forbidden:
                failures.append({"id": item["id"], "lang": item["lang"], "recall": recall,
                                 "missing": sorted(expected.difference(names)), "must_not": forbidden,
                                 "top_k": names})
    if not recalls:
        raise ValueError(f"{path}: no evaluation items")
    return {"items": len(recalls), "top_k": top_k, "mean_recall_at_k": sum(recalls) / len(recalls),
            "must_not_violations": violations,
            "per_language_recall": {lang: sum(values) / len(values) for lang, values in sorted(languages.items())},
            "failing_items": failures}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("file", metavar="FILE")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=0.9)
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.min_recall) or not 0 <= args.min_recall <= 1:
            raise ValueError("min-recall must be between 0 and 1")
        metrics = evaluate_file(args.file, top_k=args.top_k)
    except (OSError, ValueError, TypeError) as exc:
        print(f"terraproof.router.evaluate: error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2))
    return int(metrics["mean_recall_at_k"] < args.min_recall or metrics["must_not_violations"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
