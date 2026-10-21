"""Local STAC Item inspection. Only files on disk are read; nothing is fetched."""

from __future__ import annotations

import json
import os

from terraproof._common import InputError


def inspect_stac_item(path: str | os.PathLike) -> dict:
    """Describe a local STAC Item: identity, time, projection, and asset band scaling."""
    path = os.fspath(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("type") != "Feature" or "stac_version" not in data:
        raise InputError(f"not a STAC Item (needs \"type\": \"Feature\" and \"stac_version\"): {path}")

    properties = data.get("properties") or {}
    assets = {}
    for key, asset in sorted((data.get("assets") or {}).items()):
        bands = [
            {"scale": band.get("scale"), "offset": band.get("offset")}
            for band in (asset.get("raster:bands") or [])
        ]
        assets[key] = {
            "href": asset.get("href"),
            "type": asset.get("type"),
            "roles": list(asset.get("roles") or []),
            "bands": bands,
        }

    return {
        "kind": "stac",
        "path": path,
        "id": data.get("id"),
        "collection": data.get("collection"),
        "datetime": properties.get("datetime"),
        "start_datetime": properties.get("start_datetime"),
        "end_datetime": properties.get("end_datetime"),
        "bbox": data.get("bbox"),
        "proj_epsg": properties.get("proj:epsg"),
        "proj_code": properties.get("proj:code"),
        "assets": assets,
    }
