"""SAR checks: sar.value_domain and sar.geocoded.

sar.value_domain is a plausibility screen on the declared scale of the backscatter values.
It can tell that linear and decibel values have been confused; it cannot tell that the
calibration chain, speckle filtering, or terrain correction were done correctly.

sar.geocoded reads the geometry GDAL reports for the file: a GCP-only raster has neither a
CRS nor a real geotransform, so pixel coordinates are sensor- or slant-range coordinates.
"""

from __future__ import annotations

import warnings

import numpy as np
import rasterio
from rasterio.enums import Resampling

from terraproof.checks.base import FAIL, NOT_RUN, PASS, result

# One sample every STRIDE x STRIDE pixels, windowed so large SAR scenes stay cheap.
STRIDE = 8

# sigma0 in dB: p1 and p99 of a terrestrial surface scene sit well inside this window.
DB_MIN_P1 = -50.0
DB_MAX_P99 = 15.0

# sigma0 linear: non-negative, and a p99 at or below this catches a dB domain declared linear.
LINEAR_MIN = 0.0
LINEAR_MAX_P99 = 5.0

# A linear declaration with values entirely inside [0, 1] is the signature of dB data that
# was written without the log; a dB declaration with values entirely in [0, 1] is the
# signature of linear data (or of a fraction-like input).
UNIT_INTERVAL = (0.0, 1.0)

SAR_EXPECTS = ("sigma0-db", "sigma0-linear")


def _sampled_values(dataset: dict) -> tuple[np.ndarray, dict]:
    """Fixed-stride sample of band 1 with the raster's scale/offset applied."""
    with rasterio.open(dataset["path"]) as src:
        data = src.read(1, masked=True, out_shape=src.shape, resampling=Resampling.nearest)
    rows = np.arange(0, data.shape[0], STRIDE)
    cols = np.arange(0, data.shape[1], STRIDE)
    sample = data[np.ix_(rows, cols)]
    values = np.ma.compressed(sample).astype(np.float64)
    band = dataset["bands"][0]
    scale, offset = band["scale"], band["offset"]
    if scale != 1.0 or offset != 0.0:
        values = values * scale + offset
    info = {"stride": STRIDE, "scale": scale, "offset": offset, "sampled_pixels": int(values.size)}
    return values, info


def check_value_domain(rasters: list[dict], expect: str | None) -> list:
    """Screen sampled backscatter values against the domain declared by `expect`."""
    if expect not in SAR_EXPECTS:
        return [
            result(
                "sar.value_domain",
                NOT_RUN,
                f"No SAR scale declared (sar_expect must be one of {', '.join(SAR_EXPECTS)}); "
                "the value domain cannot be checked.",
                inputs=[dataset["path"] for dataset in rasters],
                sar_expect=expect,
            )
        ]
    if not rasters:
        return [
            result(
                "sar.value_domain",
                NOT_RUN,
                f"Scale '{expect}' declared, but no raster input was given.",
                sar_expect=expect,
            )
        ]

    results = []
    for dataset in rasters:
        values, info = _sampled_values(dataset)
        path = dataset["path"]
        evidence = {
            "input": path,
            "sar_expect": expect,
            "stride": STRIDE,
            "scale": info["scale"],
            "offset": info["offset"],
            "sampled_pixels": info["sampled_pixels"],
        }
        if values.size == 0:
            return_results = [
                result(
                    "sar.value_domain",
                    NOT_RUN,
                    f"No valid pixels were sampled in {path}; the value domain was not evaluated.",
                    **evidence,
                )
            ]
            results.extend(return_results)
            continue

        finite = values[np.isfinite(values)]
        if finite.size != values.size:
            results.append(
                result(
                    "sar.value_domain",
                    FAIL,
                    f"{values.size - finite.size} of {values.size} sampled pixels in {path} are NaN or infinite "
                    "after scale and offset were applied; this is a data error and is not passed.",
                    **evidence,
                )
            )
            continue
        p1, p99 = (float(x) for x in np.percentile(values, [1, 99]))
        vmin, vmax = float(values.min()), float(values.max())
        evidence.update({"min": vmin, "max": vmax, "p1": p1, "p99": p99})

        if expect == "sigma0-db":
            in_db_domain = DB_MIN_P1 <= p1 and p99 <= DB_MAX_P99
            looks_linear = UNIT_INTERVAL[0] <= vmin and vmax <= UNIT_INTERVAL[1]
            # A whole raster inside [0, 1] sits inside the decibel window too, so the unit-interval
            # signature has to be tested before the domain test or it would be a false pass.
            if looks_linear:
                results.append(
                    result(
                        "sar.value_domain",
                        FAIL,
                        f"sigma0 is declared as decibel but every sampled value in {path} lies inside [0, 1] "
                        f"(min={vmin:.4g}, max={vmax:.4g}). One possible cause is linear sigma0 written without "
                        "the log; a wrong calibration or a fraction-like input can give the same signature.",
                        **evidence,
                    )
                )
                continue
            if in_db_domain:
                results.append(
                    result(
                        "sar.value_domain",
                        PASS,
                        f"Sampled sigma0 values in {path} are in the decibel domain (p1={p1:.4g} dB, "
                        f"p99={p99:.4g} dB, expected within [{DB_MIN_P1:g}, {DB_MAX_P99:g}] dB). "
                        "This is a domain screen; it does not verify the calibration chain.",
                        **evidence,
                    )
                )
                continue
            results.append(
                result(
                    "sar.value_domain",
                    FAIL,
                    f"Sampled sigma0 values in {path} are outside the decibel domain (p1={p1:.4g} dB, "
                    f"p99={p99:.4g} dB, expected within [{DB_MIN_P1:g}, {DB_MAX_P99:g}] dB). One possible cause is "
                    "that linear values were labelled as decibel.",
                    **evidence,
                )
            )
            continue

        in_linear_domain = vmin >= LINEAR_MIN and p99 <= LINEAR_MAX_P99
        if in_linear_domain:
            results.append(
                result(
                    "sar.value_domain",
                    PASS,
                    f"Sampled sigma0 values in {path} are in the linear domain (min={vmin:.4g} >= "
                    f"{LINEAR_MIN:g}, p99={p99:.4g} <= {LINEAR_MAX_P99:g}). This is a domain screen; it does not "
                    "verify the calibration chain.",
                    **evidence,
                )
            )
            continue
        if vmin < LINEAR_MIN:
            results.append(
                result(
                    "sar.value_domain",
                    FAIL,
                    f"sigma0 is declared as linear but some sampled pixels in {path} are negative "
                    f"(min={vmin:.4g}). Linear backscatter cannot be negative; one possible cause is that "
                    "decibel values were written under a linear declaration.",
                    **evidence,
                )
            )
            continue
        results.append(
            result(
                "sar.value_domain",
                FAIL,
                f"Sampled sigma0 values in {path} exceed the linear domain (p99={p99:.4g} > "
                f"{LINEAR_MAX_P99:g}). One possible cause is that decibel values were written under a linear "
                "declaration.",
                **evidence,
            )
        )
    return results


def _is_identity(transform) -> bool:
    return tuple(transform) == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def check_geocoded(rasters: list[dict]) -> list:
    """A raster is geocoded when it carries both a CRS and a real geotransform.

    GCP-only geometry (no CRS, no transform, ground control points instead) means the pixel
    coordinates are not map coordinates. An identity transform is pixel coordinates too.
    """
    if not rasters:
        return [
            result("sar.geocoded", NOT_RUN, "No raster input to check for geocoding.")
        ]

    results = []
    for dataset in rasters:
        path = dataset["path"]
        crs = dataset["crs"]
        transform = dataset["transform"]
        with rasterio.open(path) as src:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gcps, gcp_crs = src.gcps
        gcp_count = len(list(gcps)) if gcps else 0
        evidence = {
            "input": path,
            "crs_defined": crs is not None,
            "epsg": crs["epsg"] if crs else None,
            "transform": list(transform),
            "identity_transform": _is_identity(transform),
            "gcp_count": gcp_count,
            "gcp_crs": gcp_crs.to_string() if gcp_crs else None,
        }
        if crs is None and gcp_count:
            results.append(
                result(
                    "sar.geocoded",
                    FAIL,
                    f"{path} is not geocoded: GCP-only geometry with {gcp_count} ground control points and no "
                    "CRS or geotransform. Pixel coordinates are sensor or slant-range coordinates, not map "
                    "coordinates; apply a terrain correction before spatial analysis.",
                    **evidence,
                )
            )
            continue
        if crs is None:
            results.append(
                result(
                    "sar.geocoded",
                    FAIL,
                    f"{path} is not geocoded: no CRS and no ground control points, so its pixels cannot be "
                    "placed on the Earth.",
                    **evidence,
                )
            )
            continue
        if _is_identity(transform):
            results.append(
                result(
                    "sar.geocoded",
                    FAIL,
                    f"{path} is not geocoded: the transform is the identity, so pixel indices are being read as "
                    "coordinates. Apply a terrain correction before spatial analysis.",
                    **evidence,
                )
            )
            continue
        results.append(
            result(
                "sar.geocoded",
                PASS,
                f"{path} carries a CRS ({evidence['epsg']}) and a non-identity geotransform, so its pixels are "
                "map coordinates.",
                **evidence,
            )
        )
    return results