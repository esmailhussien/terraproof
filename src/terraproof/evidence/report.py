"""Evidence report: a deterministic JSON document and Markdown renderings in English and Arabic."""

from __future__ import annotations

import json

from terraproof import __version__
from terraproof._common import jsonable, sha256_and_size
from terraproof.checks.base import CheckResult
from terraproof.evidence.grade import ADVISORY, CHECKS_PASSED, DECISION, REVIEW, grade_for

SCHEMA_VERSION = "terraproof.evidence/0.2"
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
        "grades": {DECISION: "Decision-grade", CHECKS_PASSED: "Checks passed (coverage not assessed)",
                   REVIEW: "Review required", ADVISORY: "Advisory only"},
        "statuses": {"pass": "pass", "warn": "warn", "fail": "fail", "not-run": "not-run"},
        "checks": "Checks",
        "inputs": "Inputs",
        "parameters": "Parameters",
        "versions": "Tool versions",
        "limitation": "Limitation",
        "limitation_text": LIMITATION_EN,
        "no_checks": "No checks ran.",
        "none": "none",
        "coverage": "Coverage",
        "assessed": "Assessed against the declared verification contract.",
        "unassessed": ("Not assessed: no verification contract was declared, so passing checks do not show that "
                       "the output is fit for a decision."),
        "not_checked": "Applicable checks that did not run, and what would enable them:",
        "all_ran": "Every applicable catalogue check ran.",
        "cols_checks": ("Check", "Status", "Input", "Message"),
        "cols_inputs": ("Role", "Path", "Kind", "SHA-256", "Bytes"),
        "roles": {
            "input": "input",
            "compare-to": "compare-to",
            "reference-input": "reference-input",
            "dem": "dem",
            "index-band": "index source band",
            "stack-layer": "stack layer",
            "vertical-source": "vertical source",
            "support-source": "support source",
            "qa-source": "QA source band",
            "buffer-source": "buffer source",
            "nir": "NIR source",
            "red": "red source",
            "qa": "qa",
            "accuracy-samples": "accuracy-samples",
            "class-areas": "class-areas",
            "manifest": "manifest",
            "contract": "verification contract",
            "plan": "plan",
        },
    },
    "ar": {
        "title": "تقرير أدلة Terraproof",
        "grade": "الدرجة",
        "grades": {DECISION: "جاهز للقرار", CHECKS_PASSED: "الفحوصات نجحت (التغطية غير مُقيَّمة)",
                   REVIEW: "يحتاج مراجعة", ADVISORY: "استرشادي فقط"},
        "statuses": {"pass": "ناجح", "warn": "تحذير", "fail": "فشل", "not-run": "لم يُنفَّذ"},
        "checks": "الفحوصات",
        "inputs": "المدخلات",
        "parameters": "المعاملات",
        "versions": "إصدارات الأدوات",
        "limitation": "القيود",
        "limitation_text": LIMITATION_AR,
        "no_checks": "لم يُنفَّذ أي فحص.",
        "none": "لا شيء",
        "coverage": "التغطية",
        "assessed": "قُيِّمت مقابل عقد التحقق المُعلَن.",
        "unassessed": ("غير مُقيَّمة: لم يُعلَن عقد تحقق، لذا نجاح الفحوصات لا يُثبت أن المُخرَج صالح "
                       "لاتخاذ قرار."),
        "not_checked": "فحوصات تنطبق ولم تُنفَّذ، وما يلزم لتشغيلها:",
        "all_ran": "نُفِّذ كل فحص منطبق من الكتالوج.",
        "cols_checks": ("الفحص", "الحالة", "المدخل", "الرسالة"),
        "cols_inputs": ("الدور", "المسار", "النوع", "SHA-256", "الحجم (بايت)"),
        "roles": {
            "input": "مدخل",
            "compare-to": "مرجع المقارنة",
            "reference-input": "مدخل مرجعي",
            "dem": "نموذج الارتفاع الرقمي",
            "index-band": "نطاق مصدر للمؤشر",
            "stack-layer": "طبقة من السلسلة",
            "vertical-source": "مصدر رأسي",
            "support-source": "مصدر نطاق البيانات الصالحة",
            "qa-source": "النطاق المصدر لضبط الجودة",
            "buffer-source": "مصدر النطاق العازل",
            "nir": "مصدر الأشعة تحت الحمراء القريبة",
            "red": "مصدر الحزمة الحمراء",
            "qa": "ضبط الجودة",
            "accuracy-samples": "عينات الدقة",
            "class-areas": "مساحات الفئات",
            "manifest": "بيان المنشأ",
            "contract": "عقد التحقق",
            "plan": "خطة",
        },
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
    contract: dict | str | None = None,
) -> dict:
    """Assemble the report. It holds no timestamps, so identical inputs give identical JSON.

    `grade` is the grade to act on: the contract's grade when one is declared, otherwise the grade the
    checks support on their own, which is never decision-grade. `coverage` says whether coverage was
    assessed and lists the applicable checks that did not run."""
    ordered = sorted(results, key=lambda result: (result.id, result.message))
    report = {
        "schema_version": SCHEMA_VERSION,
        "grade": grade_for(results),
        "checks": [result.to_dict() for result in ordered],
        "inputs": sorted(inputs, key=lambda record: (record["role"], record["path"])),
        "parameters": parameters,
        "tool_versions": tool_versions(),
        "limitation": LIMITATION_EN,
    }
    if contract is not None:
        from terraproof.evidence.contract import coverage, diagnostics, load_contract
        from pathlib import Path
        from terraproof.evidence.bundle import capture_companions
        normalized, record = load_contract(contract, with_record=True)
        if record:
            report['inputs'].append(record)
            report['inputs'].sort(key=lambda r: (r['role'], r['path']))
        report['companions'] = capture_companions(report, Path.cwd())
        report["verification"] = coverage(report, normalized)
        report["diagnostics"] = diagnostics(report)
        report["grade"] = report["verification"]["grade"]
    report["coverage"] = coverage_summary(report)
    return report


def coverage_summary(report: dict) -> dict:
    """Whether coverage was assessed, and the catalogue checks that apply to the checked inputs but did not run."""
    from terraproof._common import assets_root
    catalog = json.loads((assets_root() / "routing" / "checks.json").read_text(encoding="utf-8"))["checks"]
    kinds = {record["kind"] for record in report["inputs"] if record["role"] == "input"}
    ran = {check["id"] for check in report["checks"]}
    if "plan" in report["parameters"]:  # a plan preflight has no output whose coverage it could assess
        return {"assessed": False, "not_checked": []}
    not_checked = [{"check": check_id, "description": entry["description"], "enabled_by": entry["enabled_by"]}
                   for check_id, entry in sorted(catalog.items())
                   if entry.get("enabled_by") and kinds & set(entry["applies_to"]) and check_id not in ran]
    return {"assessed": "verification" in report, "not_checked": not_checked}


def report_exit_code(report: dict) -> int:
    from terraproof.evidence.grade import EXIT_CODES
    return EXIT_CODES[report["grade"]]


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

    if "verification" in report:
        verification = report["verification"]
        title = "Verification contract" if lang == "en" else "عقد التحقق"
        lines[4:4] = [f"## {title}", "", f"**{verification['status']}** — "
                       f"{verification['passed']}/{verification['required']}; "
                       f"{labels['grades'][verification['grade']]}", "",
                       ("| Path | Required check | Status |" if lang == 'en' else
                        "| المسار | الفحص المطلوب | الحالة |"), "|---|---|---|"] + [
            f"| {_cell(r['path'])} | {_cell(r['check'])} | {_cell(r['status'])} |"
            for r in verification['requirements']] + [""]

    if "coverage" in report:
        coverage = report["coverage"]
        section = [f"## {labels['coverage']}", "", labels["assessed" if coverage["assessed"] else "unassessed"], ""]
        if coverage["not_checked"]:
            section += [labels["not_checked"], ""] + [
                f"- {_code(item['check'])}: " + ", ".join(_code(name) for name in item["enabled_by"])
                for item in coverage["not_checked"]] + [""]
        else:
            section += [labels["all_ran"], ""]
        lines[lines.index(f"## {labels['checks']}"):lines.index(f"## {labels['checks']}")] = section

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
