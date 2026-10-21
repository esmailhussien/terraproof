"""STAC checks: stac.provenance warns when an Item lacks a time or a projection code."""

from __future__ import annotations

from terraproof.checks.base import PASS, WARN, result


def check_provenance(dataset: dict) -> list:
    path = dataset["path"]
    missing = []
    has_time = dataset["datetime"] is not None or (
        dataset["start_datetime"] is not None and dataset["end_datetime"] is not None
    )
    if not has_time:
        missing.append("datetime")
    if dataset["proj_code"] is None and dataset["proj_epsg"] is None:
        missing.append("projection code (proj:code or proj:epsg)")

    evidence = {
        "input": path,
        "item_id": dataset["id"],
        "datetime": dataset["datetime"],
        "proj_code": dataset["proj_code"],
        "proj_epsg": dataset["proj_epsg"],
    }
    if missing:
        return [
            result(
                "stac.provenance",
                WARN,
                f"STAC item {path} is missing: {', '.join(missing)}.",
                **evidence,
            )
        ]
    return [result("stac.provenance", PASS, f"STAC item {path} records time and projection.", **evidence)]
