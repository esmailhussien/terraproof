"""Portable SVG cartography and HTML evidence, with no plotting dependency or remote assets."""
from __future__ import annotations

import base64
from html import escape

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile


COLORS = np.array([[49, 54, 149], [69, 170, 211], [255, 255, 191], [244, 109, 67], [165, 0, 38]])


def render(directory, spec, facts, summary, *, geometry=None, status='pending'):
    if status not in ('pending', 'verified', 'failed', 'incomplete'):
        raise ValueError('unknown workflow display status')
    partial = not facts['full_aoi_in_scene']
    scope = 'PARTIAL AOI - explicitly allowed' if partial else 'FULL AOI SCENE FOOTPRINT'
    coverage = 1-summary['outside_scene_fraction_native_plane']
    usable = summary['valid_fraction_within_scene']
    usable_text = 'no selected centres' if usable is None else f'{usable:.2%}'
    coverage_line = f'Requested AOI in scene: {coverage:.2%} (native plane); usable within scene: {usable_text}.'
    explanation = ('Partial-area result explicitly approved; this is not a complete map of the requested AOI.' if partial else
                   'The scene footprint covers the requested AOI; clouds and missing observations can still exclude pixels.')
    if status in ('failed', 'incomplete', 'pending'):
        explanation = 'Not an accepted scientific result. '+explanation
    banner = '#fee2e2' if status == 'failed' else '#fef3c7' if partial or status != 'verified' else '#dcfce7'
    with rasterio.open(directory/'temperature_celsius.tif') as ds:
        factor = min(1, 720/max(ds.width, ds.height))
        width, height = max(1, round(ds.width*factor)), max(1, round(ds.height*factor))
        data = ds.read(1, masked=True, out_shape=(height, width), resampling=Resampling.nearest)
        low, high = summary['min_celsius'], summary['max_celsius']
        valid = ~np.ma.getmaskarray(data)
        scaled = np.zeros(data.shape) if low is None else np.clip((data.filled(low)-low)/(high-low or 1), 0, 1)*4
        rgba = np.empty((4, height, width), dtype='uint8')
        for channel in range(3):
            rgba[channel] = np.interp(scaled, np.arange(5), COLORS[:, channel]).astype('uint8')
        rgba[3] = np.where(valid, 255, 0)
        with MemoryFile() as memory:
            with memory.open(driver='PNG', width=width, height=height, count=4, dtype='uint8') as png:
                png.write(rgba)
            payload = base64.b64encode(memory.read()).decode('ascii')
        bounds = list(ds.bounds)
        crs = ds.crs.to_string()
        inverse = ~ds.transform
        source_shape = (ds.width, ds.height)
    # The renderer receives the resolved AOI as coordinates from the workflow below, not a network overlay.
    outline = ''
    if geometry is not None:
        scale = min(920/source_shape[0], 690/source_shape[1])
        left, top = 40+(920-source_shape[0]*scale)/2, 150+(690-source_shape[1]*scale)/2
        polygons = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else [geometry]
        for polygon in polygons:
            for ring in [polygon.exterior, *polygon.interiors]:
                points = []
                for x, y in ring.coords:
                    col, row = inverse*(x, y)
                    points.append(f'{left+col*scale:.3f},{top+row*scale:.3f}')
                outline += '<polyline points="'+' '.join(points)+'" fill="none" stroke="#18232e" stroke-width="1"/>'
    stops = ''.join(f'<stop offset="{i*25}%" stop-color="rgb({r},{g},{b})"/>'
                    for i, (r, g, b) in enumerate(COLORS))
    legend = 'No usable observations' if low is None else f'{low:.2f} to {high:.2f} degrees Celsius'
    title, product = escape(spec['id']), escape(facts['product_id'])
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1020" viewBox="0 0 1000 1020" data-workflow-status="{status}">
<title>{title}: acquisition-time land surface temperature</title>
<defs><linearGradient id="temperature">{stops}</linearGradient><clipPath id="extent"><rect x="40" y="150" width="920" height="690"/></clipPath></defs>
<rect width="1000" height="1020" fill="white"/>
<g font-family="sans-serif" fill="#172c42">
<text x="40" y="40" font-size="23">Land surface temperature — degrees Celsius</text>
<text x="40" y="69" font-size="15">{title} | Acquisition: {escape(facts['date'])}</text>
<rect x="40" y="81" width="920" height="57" fill="{banner}"/>
<text x="50" y="103" font-size="17" font-weight="bold">{status.upper()} | {escape(scope)}</text>
<text x="50" y="125" font-size="14">{escape(coverage_line)}</text>
<rect x="40" y="150" width="920" height="690" fill="#e9edf1"/>
<image x="40" y="150" width="920" height="690" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{payload}"/>
<g clip-path="url(#extent)">{outline}</g>
<rect x="40" y="858" width="270" height="16" fill="url(#temperature)"/>
<text x="325" y="873" font-size="14">{escape(legend)}</text>
<text x="40" y="904" font-size="13">Gray = outside AOI or excluded/missing observations. Continuous scale, not heat-risk classes.</text>
<text x="40" y="929" font-size="12">Native grid: {escape(crs)}. Display uses nearest-neighbour thumbnail; analysis values unchanged.</text>
<text x="40" y="954" font-size="11">Source: USGS {product}</text>
<text x="40" y="979" font-size="12">Product decoding/support checked separately. No claim of absolute physical accuracy.</text>
<text x="40" y="1003" font-size="12">{escape(explanation)}</text>
</g></svg>'''
    (directory/'map.svg').write_text(svg, encoding='utf-8')
    rows = ''.join(f'<tr><th>{escape(key)}</th><td>{escape(str(value))}</td></tr>' for key, value in summary.items())
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{title} — Terraproof</title>
<style>body{{font:16px system-ui;max-width:1050px;margin:30px auto;padding:20px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #ddd}}img{{width:100%}}</style>
<h1>{title}</h1><p>Acquisition-time land surface temperature. Reviewer-owned intent and original product assets.</p>
<section data-workflow-status="{status}" style="background:{banner};padding:16px;border:2px solid #172c42">
<h2>Result: {status.upper()} — {escape(scope)}</h2><p><strong>{escape(coverage_line)}</strong></p>
<p>{escape(explanation)}</p><p>Scene coverage policy: {escape(facts['scene_coverage_policy'])}.
Minimum usable coverage within scene: {spec['intent']['min_valid_fraction']:.2%}.</p></section>
<p><strong>Verification status and findings: <a href="workflow.json">workflow.json</a>.</strong>
This page is a presentation of the results, not an independent certificate.</p>
<img alt="Native-grid temperature map; missing observations shown in gray" src="map.svg">
<table>{rows}</table><h2>Method</h2><p>USGS Collection 2 ST: stored DN × 0.00341802 + 149 K, then subtract 273.15.
The approved QA policy and pixel-centre AOI define usable support. No gap filling or atmospheric reprocessing.</p>
<p><a href="calibration-evidence.json">Core calibration evidence</a> · <a href="summary.json">Statistics</a></p>
<p>Surface temperature is not air temperature. QA screens and source metadata can be imperfect.
Uncertainty values describe the upstream product, not uncertainty of the mean.</p></html>'''
    (directory/'report.html').write_text(html, encoding='utf-8')
