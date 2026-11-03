"""Local scientific workflow: independent small fixtures, no model or remote data."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from terraproof._common import InputError
from terraproof.cli import main
from terraproof.workflows import approve, execute, plan, repair, verify
from terraproof.workflows.intent import SCHEMA, write, load


@pytest.fixture
def workflow(tmp_path):
    transform = from_origin(500000, 1000000, 30, 30)
    raw = np.array([[40000, 41000, 42000, 43000], [44000, 45000, 46000, 47000],
                    [48000, 49000, 0, 50000], [51000, 52000, 53000, 54000]], dtype='uint16')
    qa = np.zeros((4, 4), dtype='uint16'); qa[0, 1] = 8; qa[1, 0] = 128; qa[2, 2] = 1
    uncertainty = np.full((4, 4), 200, dtype='int16'); uncertainty[3, 3] = -9999
    for name, data, nodata in [('ST.tif', raw, 0), ('QA.tif', qa, 1), ('UQ.tif', uncertainty, -9999)]:
        with rasterio.open(tmp_path/name, 'w', driver='GTiff', width=4, height=4, count=1,
                           crs='EPSG:32632', transform=transform, dtype=data.dtype, nodata=nodata) as ds:
            ds.write(data, 1)
    aoi = {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:32632'}},
           'features': [{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [
               [[500030, 1000000], [500120, 1000000], [500120, 999880], [500030, 999880], [500030, 1000000]]]}}]}
    write(tmp_path/'aoi.geojson', aoi)
    metadata = {'LANDSAT_METADATA_FILE': {
        'PRODUCT_CONTENTS': {'LANDSAT_PRODUCT_ID': 'synthetic-development-ST', 'PROCESSING_LEVEL': 'L2SP',
            'COLLECTION_NUMBER': '02', 'FILE_NAME_BAND_ST_B10': 'ST.tif',
            'FILE_NAME_QUALITY_L1_PIXEL': 'QA.tif', 'FILE_NAME_QUALITY_L2_SURFACE_TEMPERATURE': 'UQ.tif'},
        'IMAGE_ATTRIBUTES': {'SPACECRAFT_ID': 'LANDSAT_8', 'DATE_ACQUIRED': '2025-06-15', 'SCENE_CENTER_TIME': '10:15:00Z'},
        'LEVEL2_SURFACE_TEMPERATURE_PARAMETERS': {'TEMPERATURE_MULT_BAND_ST_B10': 0.00341802,
                                                'TEMPERATURE_ADD_BAND_ST_B10': 149.0}}}
    write(tmp_path/'MTL.json', metadata)
    document = {'schema': SCHEMA, 'id': 'Development: <temperature> & QA',
        'source': {'metadata': 'MTL.json', 'representation': 'usgs-native-dn'},
        'intent': {'quantity': 'land-surface-temperature', 'unit': 'degree_Celsius', 'aoi': 'aoi.geojson',
                   'acquired_between': ['2025-01-01', '2025-12-31'], 'reject_qa_bits': [0, 3, 7],
                   'min_valid_fraction': 0.1}}
    write(tmp_path/'workflow.json', document)
    return tmp_path/'workflow.json'


def approved_run(workflow):
    approval = workflow.parent/'approval.json'
    review = plan(workflow)
    assert review['status'] == 'ready-for-review', review
    approve(workflow, approval, reviewer='development-test', expected_digest=review['spec_digest'])
    out = workflow.parent/'result'
    result = execute(approval, out)
    return approval, out, result


def test_complete_run_independent_values_summary_layout_and_evidence(workflow):
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'verified', result
    assert result['physical_accuracy_validated'] is False
    with rasterio.open(out/'temperature_celsius.tif') as ds:
        values = ds.read(1, masked=True)
        assert ds.shape == (4, 3)
        assert ds.transform.c == 500030
        assert values.mask[0, 0] and values.mask[2, 1]
        # Hand arithmetic for raw DN 42000, independent of producer globals.
        assert float(values[0, 1]) == pytest.approx(19.40684, abs=0.0001)
        assert values.count() == 10
    summary = load(out/'summary.json')
    assert summary['valid_count'] == 10 and summary['selected_count'] == 12
    assert summary['mean_product_uncertainty_kelvin'] == 2.0
    assert summary['uncertainty_valid_count'] == 9
    evidence = load(out/'calibration-evidence.json')
    assert evidence['verification']['status'] == 'verified'
    assert '.partial-' not in json.dumps(evidence)
    assert '&lt;temperature&gt; &amp; QA' in (out/'map.svg').read_text(encoding='utf-8')
    assert verify(approval, out)['status'] == 'verified'


def test_geographic_aoi_membership_uses_original_edges_on_utm_grid(workflow):
    """A four-corner UTM approximation silently changes this WGS84 rectangle."""
    from pyproj import Transformer
    to_utm = Transformer.from_crs(4326, 32636, always_xy=True)
    corners = [(32.55, 25.65), (32.75, 25.65), (32.75, 25.85), (32.55, 25.85)]
    projected = [to_utm.transform(*p) for p in corners]
    west = min(p[0] for p in projected)-60
    north = max(p[1] for p in projected)+60
    transform = from_origin(west, north, 30, 30)
    width = int(np.ceil((max(p[0] for p in projected)-west+60)/30))
    height = int(np.ceil((north-min(p[1] for p in projected)+60)/30))
    for name, value, dtype, nodata in [('ST.tif', 40000, 'uint16', 0),
                                       ('QA.tif', 0, 'uint16', 1),
                                       ('UQ.tif', 200, 'int16', -9999)]:
        with rasterio.open(workflow.parent/name, 'w', driver='GTiff', width=width, height=height,
                           count=1, crs='EPSG:32636', transform=transform, dtype=dtype, nodata=nodata) as ds:
            ds.write(np.full((height, width), value, dtype=dtype), 1)
    write(workflow.parent/'aoi.geojson', {'type': 'Polygon', 'coordinates': [corners+[corners[0]]]})
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'verified', result
    # Compute support over the ENTIRE source, independently of workflow crop/mask helpers.
    rows, cols = np.indices((height, width), dtype='float64')
    x = transform.c+(cols+0.5)*30
    y = transform.f-(rows+0.5)*30
    lon, lat = Transformer.from_crs(32636, 4326, always_xy=True).transform(x, y)
    expected = (lon >= 32.55) & (lon <= 32.75) & (lat >= 25.65) & (lat <= 25.85)
    with rasterio.open(out/'aoi.tif') as ds:
        col0, row0 = ~transform*(ds.transform.c, ds.transform.f)
        row0, col0 = round(row0), round(col0)
        delivered = np.zeros_like(expected)
        delivered[row0:row0+ds.height, col0:col0+ds.width] = ds.read(1).astype(bool)
    np.testing.assert_array_equal(delivered, expected)
    assert load(out/'summary.json')['selected_count'] == int(expected.sum())
    assert load(out/'summary.json')['valid_count'] == int(expected.sum())
    assert verify(approval, out)['status'] == 'verified'


def test_native_aoi_includes_centres_exactly_on_boundary(workflow):
    write(workflow.parent/'aoi.geojson', {'type': 'FeatureCollection',
        'crs': {'type': 'name', 'properties': {'name': 'EPSG:32632'}},
        'features': [{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon',
            'coordinates': [[[500015, 999985], [500105, 999985], [500105, 999895],
                             [500015, 999895], [500015, 999985]]]}}]})
    _, out, result = approved_run(workflow)
    assert result['status'] == 'verified'
    with rasterio.open(out/'aoi.tif') as ds:
        np.testing.assert_array_equal(ds.read(1), np.ones((4, 4), dtype='uint8'))
    assert load(out/'summary.json')['selected_count'] == 16


@pytest.mark.parametrize('artifact', ['temperature_celsius.tif', 'validity.tif', 'aoi.tif',
                                      'uncertainty_kelvin.tif', 'decoded_celsius.tif'])
def test_changed_pixel_is_detected_even_without_manifest(workflow, artifact):
    approval, out, _ = approved_run(workflow)
    with rasterio.open(out/artifact, 'r+') as ds:
        data = ds.read(1); data[1, 1] += 1; ds.write(data, 1)
    result = verify(approval, out, check_manifest=False)
    assert result['status'] == 'failed'
    assert any(f['status'] == 'fail' for f in result['findings'])


def test_repair_regenerates_once_and_preserves_bad_run(workflow):
    approval, out, _ = approved_run(workflow)
    with rasterio.open(out/'temperature_celsius.tif', 'r+') as ds:
        data = ds.read(1); data += 273.15; ds.write(data, 1)
    repaired = out.parent/'repaired'
    assert repair(approval, out, repaired)['status'] == 'verified'
    assert verify(approval, out)['status'] == 'failed'
    assert load(repaired/'repair.json')['attempts'] == 1
    with pytest.raises(InputError):
        repair(approval, repaired, out.parent/'unnecessary')


@pytest.mark.parametrize('change', ['intent', 'source', 'sidecar'])
def test_changed_approved_inputs_refuse_execution(workflow, change):
    approval, out, _ = approved_run(workflow)
    if change == 'intent':
        doc = load(workflow); doc['intent']['reject_qa_bits'] = [0]; write(workflow, doc)
    elif change == 'source':
        with rasterio.open(workflow.parent/'ST.tif', 'r+') as ds:
            data = ds.read(1); data[0, 0] += 1; ds.write(data, 1)
    else:
        (workflow.parent/'ST.tif.aux.xml').write_text('<PAMDataset/>')
    with pytest.raises(InputError, match='changed'):
        execute(approval, out.parent/'new')


def test_wrong_review_digest_and_overwrite_are_refused(workflow):
    with pytest.raises(InputError):
        approve(workflow, workflow.parent/'approval.json', reviewer='x', expected_digest='wrong')
    approval, out, _ = approved_run(workflow)
    with pytest.raises(InputError):
        execute(approval, out)


@pytest.mark.parametrize('mutation', ['date', 'scale', 'representation', 'unknown', 'qa-policy'])
def test_unresolved_product_or_intent_never_becomes_ready(workflow, mutation):
    doc = load(workflow)
    if mutation == 'date': doc['intent']['acquired_between'] = ['2026-01-01', '2026-02-01']
    if mutation == 'representation': doc['source']['representation'] = 'already-decoded-kelvin'
    if mutation == 'unknown': doc['intent']['guess_qa'] = True
    if mutation == 'qa-policy': doc['intent']['reject_qa_bits'] = [3]
    if mutation == 'scale':
        meta = load(workflow.parent/'MTL.json')
        meta['LANDSAT_METADATA_FILE']['LEVEL2_SURFACE_TEMPERATURE_PARAMETERS']['TEMPERATURE_MULT_BAND_ST_B10'] = 0.0000275
        write(workflow.parent/'MTL.json', meta)
    write(workflow, doc)
    assert plan(workflow)['status'] == 'unresolved'


def test_no_usable_pixels_are_explicit_not_false_success(workflow):
    with rasterio.open(workflow.parent/'QA.tif', 'r+') as ds:
        ds.write(np.full((4, 4), 8, dtype='uint16'), 1)
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'incomplete' and result['grade'] != 'decision-grade'
    summary = load(out/'summary.json')
    assert summary['mean_celsius'] is None and summary['valid_count'] == 0
    with pytest.raises(InputError, match='coverage'):
        repair(approval, out, out.parent/'repeat')


def test_summary_and_layout_tampering_are_detected(workflow):
    approval, out, _ = approved_run(workflow)
    summary = load(out/'summary.json'); summary['mean_celsius'] += 1; write(out/'summary.json', summary)
    assert verify(approval, out, check_manifest=False)['status'] == 'failed'
    (out/'map.svg').write_text('<svg/>')
    assert any(f['requirement']=='artifact-identity' and f['status']=='fail' for f in verify(approval, out)['findings'])


def test_cli_plan_and_explicit_approval(workflow, capsys):
    assert main(['workflow', 'plan', str(workflow)]) == 0
    result = json.loads(capsys.readouterr().out)
    approval = workflow.parent/'approval.json'
    assert main(['workflow', 'approve', str(workflow), '--out', str(approval), '--reviewer', 'test',
                 '--expect-digest', result['spec_digest']]) == 0
    capsys.readouterr()
    assert main(['workflow', 'run', str(approval), '--out', str(workflow.parent/'out')]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'verified'


@pytest.mark.parametrize('extension', ['xml', 'txt'])
def test_native_mtl_formats(workflow, extension):
    meta = load(workflow.parent/'MTL.json')
    if extension == 'xml':
        from xml.etree.ElementTree import Element, SubElement, tostring
        def fill(element, value):
            for k, v in value.items():
                child = SubElement(element, k)
                if isinstance(v, dict): fill(child, v)
                else: child.text = str(v)
        root = Element('LANDSAT_METADATA_FILE'); fill(root, meta['LANDSAT_METADATA_FILE'])
        (workflow.parent/'MTL.xml').write_bytes(tostring(root))
    else:
        def grouped(document):
            lines = []
            for k, v in document.items():
                if isinstance(v, dict): lines += ['GROUP = '+k, *grouped(v), 'END_GROUP = '+k]
                else: lines.append(f'{k} = "{v}"')
            return lines
        (workflow.parent/'MTL.txt').write_text('\n'.join(grouped(meta))+'\nEND\n')
    doc = load(workflow); doc['source']['metadata'] = 'MTL.'+extension; write(workflow, doc)
    assert approved_run(workflow)[2]['status'] == 'verified'


@pytest.mark.parametrize('extension', ['kml', 'kmz'])
def test_kml_and_kmz_boundaries(workflow, extension):
    import zipfile
    from pyproj import Transformer
    transformer = Transformer.from_crs(32632, 4326, always_xy=True)
    coords = [transformer.transform(x, y) for x, y in
              [(500035, 999995), (500115, 999995), (500115, 999885), (500035, 999885), (500035, 999995)]]
    kml = ('<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs>'
           '<LinearRing><coordinates>'+ ' '.join(f'{x},{y},0' for x,y in coords)+
           '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>')
    aoi = workflow.parent/('aoi.'+extension)
    if extension == 'kmz':
        with zipfile.ZipFile(aoi, 'w') as archive: archive.writestr('doc.kml', kml)
    else: aoi.write_text(kml)
    doc = load(workflow); doc['intent']['aoi'] = aoi.name; write(workflow, doc)
    assert approved_run(workflow)[2]['status'] == 'verified'


def test_missing_or_unreadable_outputs_can_be_regenerated(workflow):
    approval, out, _ = approved_run(workflow)
    (out/'temperature_celsius.tif').write_bytes(b'not a raster')
    assert verify(approval, out)['status'] == 'failed'
    assert repair(approval, out, out.parent/'restored')['status'] == 'verified'


def test_source_change_cannot_be_repaired_by_weakening_intent(workflow):
    approval, out, _ = approved_run(workflow)
    meta = load(workflow.parent/'MTL.json')
    meta['LANDSAT_METADATA_FILE']['IMAGE_ATTRIBUTES']['SPACECRAFT_ID'] = 'LANDSAT_9'
    write(workflow.parent/'MTL.json', meta)
    with pytest.raises(InputError): repair(approval, out, out.parent/'new')


def test_aoi_hole_and_unknown_network_geometry(workflow):
    document = load(workflow.parent/'aoi.geojson')
    document['features'][0]['geometry']['coordinates'].append(
        [[500060,999970], [500060,999940], [500090,999940], [500090,999970], [500060,999970]])
    write(workflow.parent/'aoi.geojson', document)
    approval, out, result = approved_run(workflow)
    assert result['selected_cells'] == 11
    (workflow.parent/'linked.kml').write_text('<kml><NetworkLink><Link><href>https://example.com/a.kml</href></Link></NetworkLink></kml>')
    doc = load(workflow); doc['intent']['aoi'] = 'linked.kml'; write(workflow, doc)
    assert plan(workflow)['status'] == 'unresolved'


def test_clear_qa_zero_and_subzero_temperature_are_valid(workflow):
    with rasterio.open(workflow.parent/'ST.tif', 'r+') as ds:
        data = ds.read(1); data[1, 1] = 30000; ds.write(data, 1)
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'verified'
    with rasterio.open(out/'temperature_celsius.tif') as ds:
        assert float(ds.read(1, masked=True)[1, 0]) == pytest.approx(-21.6094, abs=0.0001)


@pytest.mark.parametrize('extension,driver', [('shp', 'ESRI Shapefile'), ('gpkg', 'GPKG')])
def test_native_vector_boundary_formats(workflow, extension, driver):
    import pyogrio.raw
    import shapely
    geometry = shapely.geometry.shape(load(workflow.parent/'aoi.geojson')['features'][0]['geometry'])
    path = workflow.parent/('boundary.'+extension)
    pyogrio.raw.write(path, np.array([geometry.wkb], dtype=object), [], [],
                     driver=driver, geometry_type='Polygon', crs='EPSG:32632')
    doc = load(workflow); doc['intent']['aoi'] = path.name; write(workflow, doc)
    assert approved_run(workflow)[2]['status'] == 'verified'


def test_full_scan_catches_a_pixel_beyond_first_window(workflow):
    for name, dtype, value, nodata in [('ST.tif', 'uint16', 40000, 0), ('QA.tif', 'uint16', 0, 1),
                                      ('UQ.tif', 'int16', 200, -9999)]:
        with rasterio.open(workflow.parent/name, 'w', driver='GTiff', width=600, height=300, count=1,
                           crs=32632, transform=from_origin(500000, 1000000, 30, 30), dtype=dtype, nodata=nodata) as ds:
            ds.write(np.full((300, 600), value, dtype=dtype), 1)
    aoi = load(workflow.parent/'aoi.geojson')
    aoi['features'][0]['geometry']['coordinates'] = [[[500000,1000000], [518000,1000000],
                                                     [518000,991000], [500000,991000], [500000,1000000]]]
    write(workflow.parent/'aoi.geojson', aoi)
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'verified' and result['usable_cells'] == 180000
    with rasterio.open(out/'temperature_celsius.tif', 'r+') as ds:
        ds.write(np.array([[9]], dtype='float32'), 1, window=rasterio.windows.Window(598, 298, 1, 1))
    assert verify(approval, out, check_manifest=False)['status'] == 'failed'


def test_minimum_coverage_is_honoured_without_removing_clouds(workflow):
    doc = load(workflow); doc['intent']['min_valid_fraction'] = 1; write(workflow, doc)
    approval, out, result = approved_run(workflow)
    assert result['status'] == 'incomplete'
    assert load(out/'summary.json')['valid_count'] == 10


def test_no_overlap_is_unresolved_before_approval(workflow):
    aoi = load(workflow.parent/'aoi.geojson')
    for position in aoi['features'][0]['geometry']['coordinates'][0]: position[0] += 10000
    write(workflow.parent/'aoi.geojson', aoi)
    assert plan(workflow)['status'] == 'unresolved'
    with pytest.raises(InputError):
        approve(workflow, workflow.parent/'approval.json', reviewer='x', expected_digest='anything')


def test_missing_geometry_is_an_unresolved_plan(workflow):
    (workflow.parent/'aoi.geojson').write_text('{}')
    assert plan(workflow)['status'] == 'unresolved'


def test_count_verification_is_exact_even_for_large_scenes():
    from terraproof.workflows.lst import _summary_matches
    expected = {'valid_count': 100_000_000, 'mean_celsius': 20.0}
    assert _summary_matches(dict(expected), expected)
    assert not _summary_matches(dict(expected, valid_count=99_999_999), expected)
    assert not _summary_matches(dict(expected, valid_count=100_000_000.0), expected)
    assert not _summary_matches(dict(expected, valid_count=True), expected)
    assert not _summary_matches(dict(expected, mean_celsius=float('nan')), expected)


def test_saved_manifest_has_the_final_verification(workflow):
    approval, out, result = approved_run(workflow)
    assert load(out/'workflow.json')['verification'] == result
    assert any(f['requirement'] == 'artifact-identity' for f in result['findings'])


def test_failure_after_directory_publication_never_leaves_a_verified_report(workflow, monkeypatch):
    import terraproof.workflows.lst as lst
    approval = workflow.parent/'approval.json'
    approve(workflow, approval, reviewer='test', expected_digest=plan(workflow)['spec_digest'])
    original = lst.calibration_evidence
    def fail_on_final(directory, paths):
        if directory.name == 'result':
            raise OSError('simulated evidence write failure')
        return original(directory, paths)
    monkeypatch.setattr(lst, 'calibration_evidence', fail_on_final)
    out = workflow.parent/'result'
    with pytest.raises(OSError, match='simulated'):
        execute(approval, out)
    assert load(out/'workflow.json')['verification']['status'] == 'failed'
    assert load(out/'failure.json')['published'] is True
    assert verify(approval, out)['status'] == 'failed'
    for name in ('report.html', 'map.svg'):
        assert 'data-workflow-status="failed"' in (out/name).read_text(encoding='utf-8')


def partial_aoi(workflow):
    document = load(workflow.parent/'aoi.geojson')
    document['features'][0]['geometry']['coordinates'] = [
        [[500030,1000000],[500150,1000000],[500150,999880],[500030,999880],[500030,1000000]]]
    write(workflow.parent/'aoi.geojson', document)


def test_full_scene_coverage_is_default_and_blocks_partial_before_approval(workflow):
    partial_aoi(workflow)
    review = plan(workflow)
    assert review['status'] == 'unresolved'
    assert review['facts']['scene_coverage_policy'] == 'full-aoi'
    assert review['facts']['full_aoi_in_scene'] is False
    assert review['facts']['outside_scene_fraction_native_plane'] == 0.25
    assert '25.00%' in review['issues'][0]
    assert len(review['next_steps']) == 2
    with pytest.raises(InputError):
        approve(workflow, workflow.parent/'approval.json', reviewer='test', expected_digest=review['spec_digest'])
    assert not (workflow.parent/'approval.json').exists()
    assert not (workflow.parent/'result').exists()


def test_consistent_approval_cannot_bypass_full_coverage_gate(workflow):
    from terraproof.workflows.intent import APPROVAL, digest
    partial_aoi(workflow)
    review = plan(workflow)
    approval = workflow.parent/'manual-approval.json'
    write(approval, {'schema': APPROVAL, 'spec': str(workflow), 'spec_digest': review['spec_digest'],
        'reviewer': 'test', 'inputs': review['inputs'], 'facts_digest': digest(review['facts'])})
    with pytest.raises(InputError, match='full AOI'):
        execute(approval, workflow.parent/'result')
    assert not (workflow.parent/'result').exists()


@pytest.mark.parametrize('minimum,status', [(0.1,'verified'),(1.0,'incomplete')])
def test_explicit_partial_intent_and_visible_scientific_status(workflow, minimum, status):
    partial_aoi(workflow)
    doc = load(workflow); doc['intent'].update(scene_coverage='allow-partial', min_valid_fraction=minimum)
    write(workflow, doc)
    approval, out, result = approved_run(workflow)
    assert result['status'] == status and result['full_aoi_in_scene'] is False
    assert result['scene_coverage_policy'] == 'allow-partial'
    assert load(out/'summary.json')['outside_scene_fraction_native_plane'] == 0.25
    for name in ('report.html','map.svg'):
        content = (out/name).read_text(encoding='utf-8')
        assert f'data-workflow-status="{status}"' in content
        assert 'PARTIAL AOI - explicitly allowed' in content
        assert '75.00%' in content and '83.33%' in content
        assert 'not a complete map' in content
    assert verify(approval, out)['status'] == status
    if status == 'incomplete':
        with pytest.raises(InputError, match='coverage'):
            repair(approval, out, workflow.parent/'weaker-result')


@pytest.mark.parametrize('value', [True, None, 1, 'partial', [], {}])
def test_coverage_policy_is_strict_not_truthy(workflow, value):
    doc = load(workflow); doc['intent']['scene_coverage'] = value; write(workflow, doc)
    assert plan(workflow)['status'] == 'unresolved'


def test_legacy_intent_is_not_silently_reinterpreted(workflow):
    doc = load(workflow); doc['schema'] = 'terraproof.workflow/1'; write(workflow, doc)
    review = plan(workflow)
    assert review['status'] == 'unresolved' and 'migrate' in review['issues'][0]


def test_geographic_edges_touching_native_vertices_are_not_assumed_covered(workflow):
    from pyproj import Transformer
    transformer = Transformer.from_crs(32632, 4326, always_xy=True)
    coords = [transformer.transform(x,y) for x,y in
              [(500030,1000000),(500120,1000000),(500120,999880),(500030,999880),(500030,1000000)]]
    write(workflow.parent/'aoi.geojson', {'type':'Polygon','coordinates':[coords]})
    # Straight geographic edges can bow beyond the native footprint even if vertices touch it.
    review = plan(workflow)
    assert review['status'] == 'unresolved'
    assert review['facts']['full_aoi_in_scene'] is False
    doc = load(workflow); doc['intent']['scene_coverage'] = 'allow-partial'; write(workflow,doc)
    assert plan(workflow)['status'] == 'ready-for-review'


def test_changed_coverage_policy_invalidates_approval(workflow):
    approval, out, _ = approved_run(workflow)
    doc = load(workflow); doc['intent']['scene_coverage'] = 'allow-partial'; write(workflow, doc)
    with pytest.raises(InputError, match='changed'):
        verify(approval, out)


@pytest.mark.parametrize('partial', [False, True])
def test_cli_template_writes_explicit_coverage_choice(workflow, capsys, partial):
    template = workflow.parent/'draft.json'
    args = ['workflow','init',str(template),'--metadata',str(workflow.parent/'MTL.json'),
        '--aoi',str(workflow.parent/'aoi.geojson'),'--start','2025-01-01','--end','2025-12-31',
        '--reject-qa-bits','0','3','7','--min-valid-fraction','0.1']
    assert main(args+(['--allow-partial'] if partial else [])) == 0
    capsys.readouterr()
    doc = load(template)
    assert doc['schema'] == SCHEMA
    assert doc['intent']['scene_coverage'] == ('allow-partial' if partial else 'full-aoi')


def test_full_footprint_does_not_imply_complete_observations(workflow):
    doc = load(workflow); doc['intent']['min_valid_fraction'] = 1; write(workflow, doc)
    _, out, result = approved_run(workflow)
    assert result['status'] == 'incomplete' and result['full_aoi_in_scene'] is True
    for name in ('report.html','map.svg'):
        content = (out/name).read_text(encoding='utf-8')
        assert 'data-workflow-status="incomplete"' in content
        assert 'FULL AOI SCENE FOOTPRINT' in content and 'Not an accepted scientific result' in content


def test_final_verification_failure_updates_visible_delivery(workflow, monkeypatch):
    import terraproof.workflows.lst as lst
    original = lst.verify
    def fail_final(approval, directory, **kwargs):
        result = original(approval, directory, **kwargs)
        if Path(directory).name == 'result':
            result.update(status='failed', grade='advisory-only')
        return result
    monkeypatch.setattr(lst, 'verify', fail_final)
    _, out, result = approved_run(workflow)
    assert result['status'] == load(out/'workflow.json')['verification']['status'] == 'failed'
    for name in ('report.html','map.svg'):
        assert 'data-workflow-status="failed"' in (out/name).read_text(encoding='utf-8')
