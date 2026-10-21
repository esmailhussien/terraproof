"""Evidence report: a deterministic JSON document and Markdown renderings in English and Arabic."""

from __future__ import annotations

import json

from terraproof import __version__
from terraproof._common import jsonable, sha256_and_size
from terraproof.checks.base import CheckResult
from terraproof.evidence.grade import ADVISORY, DECISION, REVIEW, grade_for

SCHEMA_VERSION = "terraproof.evidence/0.1"
LIMITATION_EN = (
    "The grade describes the data path and the checks that ran. "
    "It is not a certification of survey, engineering, legal, or safety fitness."
)
LIMITATION_AR = (
    "تصف الدرجة مسار البيانات والفحوصات التي نُفِّذت. "
    "وهي ليست شهادة بملاءمة المسح أو الهندسة أو الأمور القانونية أو السلامة."
)

LABELS = {
    "en": {
        "title": "Terraproof evidence report",
        "grade": "Grade",
        "grades": {DECISION: "Decision-grade", REVIEW: "Review required", ADVISORY: "Advisory only"},
        "statuses": {"pass": "pass", "warn": "warn", "fail": "fail", "not-run": "not-run"},
        "checks": "Checks",
        "inputs": "Inputs",
        "parameters": "Parameters",
        "versions": "Tool versions",
        "limitation": "Limitation",
        "limitation_text": LIMITATION_EN,
        "no_checks": "No checks ran.",
        "none": "none",
        "cols_checks": ("Check", "Status", "Input", "Message"),
        "cols_inputs": ("Role", "Path", "Kind", "SHA-256", "Bytes"),
        "roles": {"input": "input", "compare-to": "compare-to"},
    },
    "ar": {
        "title": "تقرير أدلة Terraproof",
        "grade": "الدرجة",
        "grades": {DECISION: "جاهز للقرار", REVIEW: "يحتاج مراجعة", ADVISORY: "استرشادي فقط"},
        "statuses": {"pass": "ناجح", "warn": "تحذير", "fail": "فشل", "not-run": "لم يُنفَّذ"},
        "checks": "الفحوصات",
        "inputs": "المدخلات",
        "parameters": "المعاملات",
        "versions": "إصدارات الأدوات",
        "limitation": "القيود",
        "limitation_text": LIMITATION_AR,
        "no_checks": "لم يُنفَّذ أي فحص.",
        "none": "لا شيء",
        "cols_checks": ("الفحص", "الحالة", "المدخل", "الرسالة"),
        "cols_inputs": ("الدور", "المسار", "النوع", "SHA-256", "الحجم (بايت)"),
        "roles": {"input": "مدخل", "compare-to": "مرجع المقارنة"},
    },
}


def tool_versions() -> dict:
    import numpy
    import pyogrio
    import pyproj
    import rasterio
    import shapely

    return {
        "terraproof": __version__,
        "pyproj": pyproj.__version__,
        "shapely": shapely.__version__,
        "numpy": numpy.__version__,
        "pyogrio": pyogrio.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
    }


def input_record(path: str, role: str, kind: str) -> dict:
    digest, size = sha256_and_size(path)
    return {"path": path, "role": role, "kind": kind, "sha256": digest, "bytes": size}


def build_report(
    *,
    inputs: list[dict],
    results: list[CheckResult],
    parameters: dict,
) -> dict:
    """Assemble the report. It holds no timestamps, so identical inputs give identical JSON."""
    ordered = sorted(results, key=lambda result: (result.id, result.message))
    return {
        "schema_version": SCHEMA_VERSION,
        "grade": grade_for(results),
        "checks": [result.to_dict() for result in ordered],
        "inputs": sorted(inputs, key=lambda record: (record["role"], record["path"])),
        "parameters": parameters,
        "tool_versions": tool_versions(),
        "limitation": LIMITATION_EN,
    }


def to_json(report: dict) -> str:
    return json.dumps(jsonable(report), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _code(text: object) -> str:
    return f"`{text}`"


def _param_value(value: object, labels: dict) -> str:
    if value is None:
        return labels["none"]
    if isinstance(value, bool):
        return "true" if value else "false"
    return _code(value)


def render_markdown(report: dict, lang: str = "en") -> str:
    if lang not in LABELS:
        raise ValueError(f"unsupported language: {lang!r}")
    labels = LABELS[lang]
    lines = [
        f"# {labels['title']}",
        "",
        f"**{labels['grade']}:** {labels['grades'][report['grade']]}",
        "",
        f"## {labels['checks']}",
        "",
    ]

    if report["checks"]:
        lines.append("| " + " | ".join(labels["cols_checks"]) + " |")
        lines.append("|---|---|---|---|")
        for check in report["checks"]:
            evidence = check["evidence"]
            paths = [evidence["input"]] if "input" in evidence else list(evidence.get("inputs", []))
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(_code(check["id"])),
                        _cell(labels["statuses"][check["status"]]),
                        _cell(", ".join(_code(path) for path in paths)),
                        _cell(check["message"]),
                    ]
                )
                + " |"
            )
    else:
        lines.append(labels["no_checks"])
    lines.append("")

    lines += [f"## {labels['inputs']}", ""]
    lines.append("| " + " | ".join(labels["cols_inputs"]) + " |")
    lines.append("|---|---|---|---|---|")
    for record in report["inputs"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(labels["roles"][record["role"]]),
                    _cell(_code(record["path"])),
                    _cell(record["kind"]),
                    _cell(_code(record["sha256"])),
                    _cell(record["bytes"]),
                ]
            )
            + " |"
        )
    lines.append("")

    lines += [f"## {labels['parameters']}", ""]
    for key, value in report["parameters"].items():
        lines.append(f"- {_code(key)}: {_param_value(value, labels)}")
    lines.append("")

    lines += [f"## {labels['versions']}", ""]
    for key, value in report["tool_versions"].items():
        lines.append(f"- {_code(key)}: {_code(value)}")
    lines.append("")

    lines += [f"## {labels['limitation']}", "", labels["limitation_text"], ""]
    return "\n".join(lines)
