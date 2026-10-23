"""Fixtures and oracles for the `stac-and-cloud-access` task specs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pyproj
import rasterio

from terraproof.evals.fixtures import FLOAT_NODATA, UTM, read_raster, read_transform, write_cog, write_raster, write_stac_item
from terraproof.evals.harness import Step
from terraproof.evals.oracles import Oracle
from terraproof.evals.recipes._util import (
    check_step,
    correct,
    manifest_step,
    recipe,
    results_for,
    write_manifest_file,
    wrong,
)
from terraproof.provenance import verify_manifest

SAS_PATTERNS = ("sig=", "se=", "sp=", "token=")


def _s2_item(path: Path, *, baseline: str = "05.00", href: str | None = None) -> str:
    return write_stac_item(
        path,
        item_id="S2B_MSIL2A_PINNED",
        datetime="2024-06-15T10:30:00Z",
        proj_code="EPSG:32636",
        extra_properties={"s2:processing_baseline": baseline, "eo:cloud_cover": 8.5, "proj:epsg": 32636},
        assets={
            "B04": {
                "href": href or "https://catalog.example.invalid/items/S2B_MSIL2A_PINNED/B04.tif",
                "type": "image/tiff; application=geotiff",
                "raster:bands": [{"scale": 0.0001, "offset": -0.1, "nodata": 0}],
            }
        },
    )


def _dn_raster(path: Path, values=None) -> str:
    rows, cols = np.indices((16, 16))
    dn = (1500 + 40 * ((rows + cols) % 20)).astype("uint16")
    dn[0, 0] = 2500
    dn[0, 1] = 0
    return write_raster(path, dn, crs=UTM, nodata=0, dtype="uint16", scale=0.0001, offset=-0.1)


def _sr_from_dn(dn: np.ndarray) -> np.ndarray:
    output = np.full(dn.shape, FLOAT_NODATA, dtype="float32")
    valid = dn != 0
    output[valid] = dn[valid] * 0.0001 - 0.1
    return output


def stac_pinned_search(root: Path):
    """Task 1: a pinned search whose run record can be re-verified."""
    item = _s2_item(root / "source-item.json")
    dn = _dn_raster(root / "red_dn.tif")
    with rasterio.open(dn) as src:
        dn_values = src.read(1)
    sr = write_raster(root / "sr_red.tif", _sr_from_dn(dn_values), crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    steps = [
        check_step("check source-item.json", [item]),
        manifest_step(
            "write_manifest(inputs=[red_dn.tif, source-item.json], outputs=[sr_red.tif]) + verify_manifest",
            root,
            inputs=[dn, item],
            outputs=[sr],
            parameters={
                "api": "https://catalog.example.invalid",
                "collection": "sentinel-2-l2a",
                "bbox": [31.2, 30.05, 31.23, 30.07],
                "datetime": "2024-06-01T00:00:00Z/2024-06-30T23:59:59Z",
                "query": {"eo:cloud_cover": {"lt": 20}},
            },
            stac_items=[item],
            manifest_name="run.manifest.json",
        ),
        check_step(
            "run_checks(['source-item.json'], time_range=('2024-06-01','2024-06-30'))",
            [item],
            time_range=("2024-06-01T00:00:00Z", "2024-06-30T23:59:59Z"),
        ),
    ]
    manifest_path = root / "run.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    oracle = Oracle("deterministic manifest core, file hashes and a pinned Item identity")
    core = manifest["core"]
    recorded = {(record["role"], record["path"]): record for record in core["files"]}
    oracle.equal("recorded file roles", sorted({role for role, _path in recorded}), ["input", "output"])
    for path in (dn, item, sr):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        relative = Path(path).name
        record = recorded.get(("input", relative)) or recorded.get(("output", relative))
        oracle.require(
            f"recorded SHA-256 matches {relative}",
            record is not None and record["sha256"] == digest,
            record["sha256"] if record else None,
            digest,
        )
    oracle.require(
        "the pinned Item id, datetime and baseline are recorded",
        bool(core["stac_items"])
        and core["stac_items"][0]["id"] == "S2B_MSIL2A_PINNED"
        and core["stac_items"][0]["datetime"] == "2024-06-15T10:30:00Z",
        core["stac_items"][0] if core["stac_items"] else None,
        "id, datetime and href",
    )
    second = root / "run2.manifest.json"
    write_manifest_file(
        second,
        inputs=[dn, item],
        outputs=[sr],
        parameters=core["parameters"],
        stac_items=[item],
    )
    second_manifest = json.loads(second.read_text(encoding="utf-8"))
    oracle.equal(
        "two writes of the same run produce the same core hash",
        second_manifest["core_sha256"],
        manifest["core_sha256"],
    )
    oracle.require(
        "the creation timestamp stays outside the hashed core",
        "created" not in core and "created" in manifest["context"],
        sorted(core),
        "core without a timestamp",
    )
    text = manifest_path.read_text(encoding="utf-8")
    oracle.require(
        "no credentials or signed-URL parameters are recorded",
        not any(pattern in text for pattern in SAS_PATTERNS),
        "clean",
        "no SAS parameters",
    )
    drift = root / "drift"
    drift.mkdir()
    drifted_item = drift / "source-item.json"
    shutil.copyfile(item, drifted_item)
    drifted_dn = drift / "red_dn.tif"
    shutil.copyfile(dn, drifted_dn)
    drifted_sr = drift / "sr_red.tif"
    shutil.copyfile(sr, drifted_sr)
    write_manifest_file(
        drift / "run.manifest.json",
        inputs=[drifted_dn, drifted_item],
        outputs=[drifted_sr],
        parameters=core["parameters"],
        stac_items=[drifted_item],
    )
    reprocessed = json.loads(drifted_item.read_text(encoding="utf-8"))
    reprocessed["properties"]["s2:processing_baseline"] = "05.10"
    drifted_item.write_text(json.dumps(reprocessed, indent=2, sort_keys=True), encoding="utf-8")
    drift_result = verify_manifest(drift / "run.manifest.json")
    oracle.require(
        "a reprocessed Item is detected as a changed file",
        drift_result.status == "fail" and "changed file" in drift_result.message,
        drift_result.message,
        "fail on a changed file",
    )
    stac_status = results_for(steps, "stac.provenance")
    provenance_status = results_for(steps, "provenance.reproducible")
    temporal_status = results_for(steps, "rs.temporal_scope")
    oracle.require(
        "stac.provenance passes on the pinned Item",
        bool(stac_status) and stac_status[0].status == "pass",
        stac_status[0].status if stac_status else None,
        "pass",
    )
    oracle.require(
        "provenance.reproducible passes on the run manifest",
        bool(provenance_status) and provenance_status[0].status == "pass",
        provenance_status[0].status if provenance_status else None,
        "pass",
    )
    oracle.require(
        "rs.temporal_scope passes for the June 2024 request",
        bool(temporal_status) and temporal_status[0].status == "pass",
        temporal_status[0].status if temporal_status else None,
        "pass",
    )
    correct_control = correct(
        "pinned-search-manifest",
        "A local Sentinel-2 L2A Item with a processing baseline, a DN input, a decoded output and a "
        "verified run manifest that records both.",
        steps,
        oracle,
    )

    nondeterministic = root / "nondeterministic"
    nondeterministic.mkdir()
    shifted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shifted_core = dict(shifted_manifest["core"])
    shifted_core["created"] = "2024-07-01T00:00:00+00:00"
    shifted_manifest["core"] = shifted_core
    shifted_manifest["core_sha256"] = _core_hash(shifted_core)
    shifted_path = root / "run_nondeterministic.manifest.json"
    shifted_path.write_text(json.dumps(shifted_manifest, indent=2, sort_keys=True), encoding="utf-8")
    shifted_steps = [
        check_step("check source-item.json", [item]),
        Step(command="verify_manifest('run_nondeterministic.manifest.json')", results=[verify_manifest(shifted_path)]),
        check_step(
            "run_checks(['source-item.json'], time_range=('2024-06-01','2024-06-30'))",
            [item],
            time_range=("2024-06-01T00:00:00Z", "2024-06-30T23:59:59Z"),
        ),
    ]
    wrong_oracle = Oracle("a timestamp inside the hashed core breaks reproducibility")
    second_shifted = dict(shifted_core)
    second_shifted["created"] = "2024-07-02T00:00:00+00:00"
    wrong_oracle.equal(
        "two writes of the same run produce the same core hash",
        _core_hash(second_shifted),
        _core_hash(shifted_core),
    )
    wrong_control = wrong(
        "timestamp-inside-core",
        "The creation timestamp is moved inside the hashed core (with a recomputed core hash), so the "
        "same run no longer reproduces; the schema verifier now rejects this extra core key.",
        shifted_steps,
        wrong_oracle,
    )

    signed_record = root / "run_record_signed.json"
    signed_record.write_text(
        json.dumps(
            {
                "api": "https://catalog.example.invalid",
                "assets": [
                    {
                        "key": "B04",
                        "href": "https://catalog.example.invalid/B04.tif?sv=2024-01-01&se=2024-12-31&sig=SECRET",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    write_manifest_file(
        root / "signed.manifest.json",
        inputs=[dn, item],
        outputs=[sr, str(signed_record)],
        parameters=core["parameters"],
        stac_items=[item],
    )
    token_steps = [
        check_step("check source-item.json", [item]),
        Step(
            command="verify_manifest('signed.manifest.json')",
            results=[verify_manifest(root / "signed.manifest.json")],
        ),
        check_step(
            "run_checks(['source-item.json'], time_range=('2024-06-01','2024-06-30'))",
            [item],
            time_range=("2024-06-01T00:00:00Z", "2024-06-30T23:59:59Z"),
        ),
    ]
    token_oracle = Oracle("the shared run record must not contain signed URLs or credentials")
    record_text = signed_record.read_text(encoding="utf-8")
    token_oracle.require(
        "no signed-URL parameters appear in the run record",
        not any(pattern in record_text for pattern in SAS_PATTERNS),
        "signed parameters present",
        "unsigned hrefs only",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "signed-href-leak",
            "The run record stores an asset href with a SAS token; file hashes match but provenance "
            "verification rejects the credential-bearing recorded JSON.",
            token_steps,
            token_oracle,
        ),
    ]
    return recipe(
        "stac-pinned-search-manifest",
        correct_control,
        wrong_controls,
        automated_scope=[
            "stac.provenance on the pinned Item, provenance.reproducible on the written manifest, rs.temporal_scope on its datetime",
            "independent SHA-256 re-hashing, core-hash determinism, timestamp-outside-core and unchanged-file verification",
            "detection of a reprocessed Item and a scan for SAS/credential parameters in the run record",
        ],
        remaining=[
            "Re-fetching by ids against the live catalog, the search conformance check and the Query extension are external/network steps; the fixture pins recorded responses instead.",
            "The answer must explain the search parameters and why only the query is not enough; prose is not graded.",
        ],
    )


def _core_hash(core: dict) -> str:
    payload = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stac_loader_double_decode(root: Path):
    """Task 2: a loader already applied the scale/offset, so decoding again is wrong."""
    rows, cols = np.indices((16, 16))
    dn_values = (1200 + 45 * ((rows + cols) % 25)).astype("uint16")
    dn_values[0, 0] = 2500
    dn_values[0, 1] = 0
    dn = write_raster(root / "red_dn.tif", dn_values, crs=UTM, nodata=0, dtype="uint16", scale=0.0001, offset=-0.1)
    sr = write_raster(root / "sr_red.tif", _sr_from_dn(dn_values), crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    item = _s2_item(root / "source-item.json")
    from terraproof.inspect import inspect_dataset

    steps = [
        check_step(
            "run_checks(['sr_red.tif'], expect='reflectance', reference_input='red_dn.tif', encoding='s2-l2a')",
            [sr],
            expect="reflectance",
            reference_input=inspect_dataset(dn),
            encoding="s2-l2a",
        )
    ]
    delivered = read_raster(sr)
    oracle = Oracle("decode once: DN 2500 -> 0.15, DN 0 -> nodata")
    oracle.close("DN 2500 decodes to 0.15", float(np.ma.getdata(delivered)[0, 0]), 0.15, 1e-6)
    oracle.require(
        "DN 0 is nodata, not -0.1 reflectance",
        bool(np.ma.getmaskarray(delivered)[0, 1]),
        "masked" if np.ma.getmaskarray(delivered)[0, 1] else "valid",
        "masked",
    )
    with rasterio.open(sr) as src:
        oracle.equal("output scale/offset is identity", (src.scales[0], src.offsets[0]), (1.0, 0.0))
        oracle.equal("nodata is declared", src.nodatavals[0], FLOAT_NODATA)
    oracle.close(
        "a second decode would give -0.099985",
        0.15 * 0.0001 - 0.1,
        -0.099985,
        1e-9,
    )
    for check_id in ("rs.scale_applied_once", "rs.reflectance_range", "raster.nodata_declared"):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} passes on the decoded output",
            bool(observed) and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "single-decode",
        "Raw DN with the asset scale/offset decoded exactly once to physical reflectance, with DN 0 as nodata.",
        steps,
        oracle,
    )

    double = np.full(dn_values.shape, FLOAT_NODATA, dtype="float32")
    valid = dn_values != 0
    double[valid] = dn_values[valid] * 0.0001 - 0.1
    double[valid] = double[valid] * 0.0001 - 0.1
    double_path = write_raster(root / "sr_red_double.tif", double, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    wrong_steps = [
        check_step(
            "run_checks(['sr_red_double.tif'], expect='reflectance', reference_input='red_dn.tif', encoding='s2-l2a')",
            [double_path],
            expect="reflectance",
            reference_input=inspect_dataset(dn),
            encoding="s2-l2a",
        )
    ]
    wrong_oracle = Oracle("double-decoded reflectance must not be published")
    wrong_values = read_raster(double_path)
    wrong_oracle.close("DN 2500 decodes to 0.15", float(np.ma.getdata(wrong_values)[0, 0]), 0.15, 1e-6)
    wrong_oracle.differs_by(
        "the double-decoded value differs from the correct reflectance",
        float(np.ma.getdata(wrong_values)[0, 0]),
        0.15,
        0.05,
    )
    wrong_control = wrong(
        "double-decoded",
        "Scale and offset are applied twice because the loader already decoded the data, giving tiny "
        "but plausible-looking values.",
        wrong_steps,
        wrong_oracle,
        notes="rs.scale_applied_once rejects this, which is exactly the gap it exists to close.",
    )

    zero_valid = np.full(dn_values.shape, FLOAT_NODATA, dtype="float32")
    zero_valid[valid] = dn_values[valid] * 0.0001 - 0.1
    zero_valid[0, 1] = -0.1
    zero_path = write_raster(root / "sr_red_zero_valid.tif", zero_valid, crs=UTM, nodata=FLOAT_NODATA, dtype="float32")
    zero_steps = [
        check_step(
            "run_checks(['sr_red_zero_valid.tif'], expect='reflectance', reference_input='red_dn.tif', encoding='s2-l2a')",
            [zero_path],
            expect="reflectance",
            reference_input=inspect_dataset(dn),
            encoding="s2-l2a",
        )
    ]
    zero_oracle = Oracle("DN 0 is nodata, so it must not decode to -0.1")
    zero_values = read_raster(zero_path)
    zero_oracle.require(
        "DN 0 is nodata in the output",
        bool(np.ma.getmaskarray(zero_values)[0, 1]),
        "masked" if np.ma.getmaskarray(zero_values)[0, 1] else "valid",
        "masked",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "zero-dn-decoded",
            "DN 0 is carried through the decode as a valid -0.1 reflectance pixel instead of nodata.",
            zero_steps,
            zero_oracle,
            notes="rs.scale_applied_once exhaustively checks source-mask preservation, including off-stride nodata.",
        ),
    ]
    return recipe(
        "stac-loader-double-decode",
        correct_control,
        wrong_controls,
        automated_scope=[
            "rs.scale_applied_once against the original DN, rs.reflectance_range and raster.nodata_declared",
            "independent DN 2500 -> 0.15 and DN 0 -> nodata controls and identity scale/offset metadata",
        ],
        remaining=[
            "The answer must state which loader (stackstac rescale=True vs rasterio/odc-stac raw DN) decoded the data; prose is not graded.",
            "Verification against the actual cloud-free control area in the live product.",
        ],
    )


def stac_windowed_cog(root: Path):
    """Task 3: a windowed COG subset of a signed remote COG, with unsigned hrefs in the record."""
    source = write_cog(
        root / "remote_cog.tif",
        np.arange(256 * 256, dtype="float32").reshape(256, 256) % 997,
        crs=UTM,
        nodata=FLOAT_NODATA,
        blocksize=128,
    )
    origin = (500000.0, 5000000.0)
    resolution = 10.0
    window_bounds = (500500.0, 4998400.0, 502500.0, 5000000.0)  # x0, y0, x1, y1 in the asset CRS
    with rasterio.open(source) as src:
        window = rasterio.windows.from_bounds(
            window_bounds[0], window_bounds[1], window_bounds[2], window_bounds[3], transform=src.transform
        )
        window = window.round_offsets().round_lengths()
        subset_values = src.read(1, window=window)
        subset_transform = rasterio.windows.transform(window, src.transform)
    aoi_subset = root / "aoi_subset.tif"
    with rasterio.open(
        aoi_subset,
        "w",
        driver="COG",
        width=subset_values.shape[1],
        height=subset_values.shape[0],
        count=1,
        dtype="float32",
        crs=UTM,
        transform=subset_transform,
        nodata=FLOAT_NODATA,
        compress="deflate",
        blocksize=64,
    ) as dst:
        dst.write(subset_values, 1)
    to_lonlat = pyproj.Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)
    lower_left = to_lonlat.transform(window_bounds[0], window_bounds[1])
    upper_right = to_lonlat.transform(window_bounds[2], window_bounds[3])
    aoi = [min(lower_left[0], upper_right[0]), min(lower_left[1], upper_right[1]), max(lower_left[0], upper_right[0]), max(lower_left[1], upper_right[1])]
    record = root / "run_record.json"
    record.write_text(
        json.dumps(
            {
                "api": "https://planetarycomputer.microsoft.com/api/stac/v1",
                "aoi_lonlat": aoi,
                "assets": [{"key": "B04", "href": "https://planetarycomputer.example.invalid/B04.tif"}],
                "window_crs": UTM,
                "window_bounds": list(_bounds_from_transform(subset_transform, subset_values.shape)),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    steps = [
        check_step("check aoi_subset.tif", [str(aoi_subset)]),
        manifest_step("verify subset and unsigned run record", root, inputs=[source],
                      outputs=[str(aoi_subset), str(record)], manifest_name="subset.manifest.json"),
    ]
    expected_bounds = _expected_window(aoi, origin, resolution)
    transform = read_transform(aoi_subset)
    actual_bounds = _bounds_from_transform(transform, subset_values.shape)
    oracle = Oracle("windowed read: the subset covers the AOI window, not the whole scene")
    for index, name in enumerate(("x0", "y0", "x1", "y1")):
        oracle.close(
            f"subset {name} matches the AOI window in the asset CRS",
            actual_bounds[index],
            expected_bounds[index],
            resolution,
        )
    oracle.equal("subset shape equals the window size", subset_values.shape, (160, 200))
    with rasterio.open(aoi_subset) as src:
        oracle.equal("subset keeps the asset CRS", src.crs.to_string(), UTM)
        oracle.equal("subset declares nodata", src.nodatavals[0], FLOAT_NODATA)
        oracle.require("subset is tiled with overviews", src.profile.get("tiled", False) and len(src.overviews(1)) > 0, list(src.overviews(1)), "overviews present")
    oracle.require(
        "subset is smaller than the whole scene",
        subset_values.size < 256 * 256,
        int(subset_values.size),
        "< 65536 pixels",
    )
    text = record.read_text(encoding="utf-8")
    oracle.require(
        "the run record stores unsigned hrefs only",
        not any(pattern in text for pattern in SAS_PATTERNS),
        "clean",
        "no SAS parameters",
    )
    for check_id in ("crs.defined", "raster.nodata_declared", "raster.cog_layout"):
        observed = results_for(steps, check_id)
        oracle.require(
            f"{check_id} passes on the delivered subset",
            bool(observed) and all(result.status == "pass" for result in observed),
            [result.status for result in observed],
            "pass",
        )
    correct_control = correct(
        "windowed-cog-subset",
        "A local remote-CRS COG, an AOI in lon/lat, a window-only read written as a COG and a run record "
        "with unsigned hrefs.",
        steps,
        oracle,
    )

    whole_scene = write_cog(root / "whole_scene.tif", read_raster(source).filled(FLOAT_NODATA), crs=UTM, nodata=FLOAT_NODATA)
    wrong_steps = [check_step("check whole_scene.tif", [whole_scene])]
    wrong_oracle = Oracle("a whole-scene copy is not a windowed AOI subset")
    wrong_transform = read_transform(whole_scene)
    wrong_bounds = _bounds_from_transform(wrong_transform, (256, 256))
    wrong_oracle.close(
        "subset x0 matches the AOI window",
        wrong_bounds[0],
        expected_bounds[0],
        resolution,
    )
    wrong_oracle.require(
        "subset is smaller than the whole scene",
        False,
        256 * 256,
        "< 65536 pixels",
    )
    wrong_control = wrong(
        "whole-scene-download",
        "The whole scene is copied into the delivery instead of the AOI window; the COG checks still pass.",
        wrong_steps,
        wrong_oracle,
    )

    signed_record = root / "run_record_signed.json"
    signed_record.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "key": "B04",
                        "href": "https://planetarycomputer.example.invalid/B04.tif?sv=2024-01-01&se=2024-12-31&sig=SECRET",
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    token_steps = [
        check_step("check aoi_subset.tif", [str(aoi_subset)]),
        manifest_step("verify subset and signed run record", root, inputs=[source],
                      outputs=[str(aoi_subset), str(signed_record)], manifest_name="signed_subset.manifest.json"),
    ]
    token_oracle = Oracle("a stored SAS token is a leak even when the COG checks pass")
    token_oracle.require(
        "no signed-URL parameters appear in the run record",
        not any(pattern in signed_record.read_text(encoding="utf-8") for pattern in SAS_PATTERNS),
        "signed parameters present",
        "unsigned hrefs only",
    )
    wrong_controls = [
        wrong_control,
        wrong(
            "signed-href-stored",
            "The run record stores a signed href with an expiring SAS token.",
            token_steps,
            token_oracle,
        ),
    ]
    return recipe(
        "stac-signed-windowed-cog-subset",
        correct_control,
        wrong_controls,
        automated_scope=[
            "crs.defined, raster.nodata_declared and raster.cog_layout on the delivered subset",
            "independent AOI-to-asset-CRS window calculation, subset bounds/shape comparison and a SAS-token scan",
        ],
        remaining=[
            "Signing at read time (planetary_computer.sign_inplace) and HTTP range requests need a live Planetary Computer account and network; the fixture is a local COG.",
            "The answer must explain the signing and windowed-read approach; prose is not graded.",
        ],
    )


def _bounds_from_transform(transform, shape) -> tuple[float, float, float, float]:
    height, width = shape
    x0, y0 = transform[2], transform[5] + height * transform[4]
    x1, y1 = transform[2] + width * transform[0], transform[5]
    return (x0, min(y0, y1), x1, max(y0, y1))


def _expected_window(aoi, origin, resolution) -> tuple[float, float, float, float]:
    transformer = pyproj.Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
    west, south = transformer.transform(aoi[0], aoi[1])
    east, north = transformer.transform(aoi[2], aoi[3])
    x0 = origin[0] + round((min(west, east) - origin[0]) / resolution) * resolution
    x1 = origin[0] + round((max(west, east) - origin[0]) / resolution) * resolution
    y1 = origin[1] - round((origin[1] - max(south, north)) / resolution) * resolution
    y0 = origin[1] - round((origin[1] - min(south, north)) / resolution) * resolution
    return (float(x0), float(y0), float(x1), float(y1))


RECIPES = {
    "stac-pinned-search-manifest": stac_pinned_search,
    "stac-loader-double-decode": stac_loader_double_decode,
    "stac-signed-windowed-cog-subset": stac_windowed_cog,
}
