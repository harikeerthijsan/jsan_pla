"""QC rule coverage and generic checks for workbooks that are not in the PLA layout."""
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE', 'local')
os.environ.setdefault('JWT_SECRET', 'test-secret')

import pytest
from openpyxl import Workbook

from app import processor
from app.ingest import parse_workbook
from app.main import rule_coverage_summary


def workbook(tmp_path, headers, rows, title='ZoneName', extra=None):
    path = tmp_path / 'customer.xlsx'; book = Workbook(); sheet = book.active; sheet.title = title
    sheet.append(headers)
    for row in rows: sheet.append(row)
    for name, columns in (extra or {}).items():
        book.create_sheet(name).append(columns)
    book.save(path)
    return parse_workbook(str(path), 'EPSG:6424')


def rules(result):
    return {r['rule_id']: r for r in result['rules']}


def findings(result, rule_id):
    return [f for f in result['findings'] if f['rule_id'] == rule_id]


def test_customer_workbook_without_pla_columns_is_not_failed_by_pla_rules(tmp_path):
    result = workbook(tmp_path, ['internal_id', 'Pole Number', 'Latitude', 'Longitude', 'Attachment Owner'],
                      [[1, 'P-1', 34.37, -118.91, 'Utility A'], [2, 'P-2', 34.371, -118.911, None]])
    assert not findings(result, 'PLA-R003'), 'missing PLA elevation columns must not fail every pole'
    status = rules(result)
    assert status['PLA-R003']['applicable'] is False and 'bottom_elev_ft' in status['PLA-R003']['reason']
    for rule_id in ('PLA-R006', 'PLA-R014', 'PLA-R020', 'PLA-R021', 'PLA-R010', 'PLA-R012', 'PLA-R030'):
        assert status[rule_id]['applicable'] is False and status[rule_id]['reason'].startswith('Not applicable: needs')
    for rule_id in ('PLA-R002', 'GEN-001', 'GEN-002'):
        assert status[rule_id]['applicable'] is True and status[rule_id]['reason'] is None
    assert not result['findings']


def test_pla_workbook_keeps_its_rules(tmp_path):
    result = workbook(tmp_path, ['internal_id', 'pole_number', 'grade_of_construction', 'latitude', 'longitude', 'bottom_elev_ft', 'top_elev_ft', 'other_1_id', 'other_1_type'],
                      [[1, 'P-1', None, 34.37, -118.91, None, None, 1, 'OTHER_POLE']], title='poles',
                      extra={'guys': ['internal_id', 'pole_number', 'guy_1_anchor_no'], 'anchors': ['internal_id', 'pole_number', 'anc_1_lat']})
    status = rules(result)
    for rule_id in ('PLA-R003', 'PLA-R006', 'PLA-R014', 'PLA-R010', 'PLA-R020'):
        assert status[rule_id]['applicable'] is True, rule_id
    assert {f['rule_id'] for f in result['findings']} >= {'PLA-R003', 'PLA-R014', 'PLA-R006'}
    assert not findings(result, 'GEN-001'), 'R003 already reports the missing geometry'


@pytest.mark.parametrize('lat,lon,message', [
    ('abc', -118.91, "Latitude 'abc' is not a number"),
    (95.0, -118.91, 'Latitude 95.0 is outside -90..90'),
    (-118.91, 34.37, 'Latitude and longitude look swapped'),
])
def test_invalid_coordinates_are_reported_with_their_column(tmp_path, lat, lon, message):
    result = workbook(tmp_path, ['internal_id', 'Pole Number', 'Latitude', 'Longitude'], [[1, 'P-1', lat, lon], [2, 'P-2', 34.37, -118.91]])
    bad = findings(result, 'GEN-002')
    assert bad and all(f['internal_id'] == 1 and f['severity'] == 'FAIL' and f['sheet'] == 'ZoneName' for f in bad)
    assert any(message in f['message'] for f in bad)
    assert result['poles'][0]['corrected_lat'] is None, 'an invalid coordinate must not place the pole'
    assert not findings(result, 'GEN-001'), 'the coordinate problem is reported once, as GEN-002'


def test_pole_without_any_location_is_reported(tmp_path):
    result = workbook(tmp_path, ['internal_id', 'Pole Number', 'Latitude', 'Longitude'], [[1, 'P-1', None, None], [2, 'P-2', 34.37, -118.91]])
    missing = findings(result, 'GEN-001')
    assert [f['internal_id'] for f in missing] == [1] and missing[0]['field'] == 'location'


class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def filter_by(self, **kwargs): return self
    def all(self): return self.rows


def geo(feature_index, pole, x, y):
    return SimpleNamespace(feature_index=feature_index, pole_internal_id=pole, x=x, y=y, match_property='pole_number')


def spatial(points, *, blocks=True, geojson=True, geo_summary=None):
    parsed = {'pole_sheet': 'ZoneName', 'findings': [], 'poles': [
        {'internal_id': i, 'pole_number': f'P-{i}'} for i in (1, 2, 3, 4)]}
    db = SimpleNamespace(query=lambda model: FakeQuery(points))
    project = SimpleNamespace(id='qc-test', units='US survey foot')
    pole_xy = {1: (100.0, 100.0), 2: (200.0, 200.0), 3: (300.0, 300.0), 4: (5000.0, 5000.0)}
    pole_block = {1: 'tile_a', 2: 'tile_a', 3: 'tile_a', 4: None}
    statuses = processor.generic_spatial_checks(db, project, parsed, [{'name': 'tile_a'}] if blocks else [], pole_xy, pole_block,
                                                object() if geojson else None, geo_summary if geo_summary is not None else ({} if geojson else None))
    return parsed['findings'], {s['rule_id']: s for s in statuses}


def test_lidar_coverage_and_geojson_agreement_checks():
    points = [geo(0, 1, 101.0, 100.0), geo(1, 2, 260.0, 200.0), geo(2, 3, 300.0, 300.0), geo(3, 3, 301.0, 300.0)]
    found, status = spatial(points)
    by_rule = {}
    for f in found: by_rule.setdefault(f['rule_id'], []).append(f['internal_id'])
    assert by_rule == {'GEN-003': [4], 'GEN-005': [2], 'GEN-006': [3], 'GEN-004': [4]}
    offset = next(f for f in found if f['rule_id'] == 'GEN-005')
    assert offset['message'].endswith('60.0 ft from the workbook location.') and offset['expected'] == 'within 10 ft'
    assert all(status[r]['applicable'] for r in ('GEN-003', 'GEN-004', 'GEN-005', 'GEN-006'))


def test_geojson_checks_are_not_applicable_without_a_usable_file():
    found, status = spatial([], geojson=False)
    assert {f['rule_id'] for f in found} == {'GEN-003'}
    assert status['GEN-004']['applicable'] is False and 'no GeoJSON' in status['GEN-004']['reason']
    _, rejected = spatial([], geo_summary={'error': 'Unsupported CRS'})
    assert 'rejected (Unsupported CRS)' in rejected['GEN-005']['reason']
    found, status = spatial([], blocks=False, geojson=False)
    assert not found and status['GEN-003']['applicable'] is False


def test_rule_coverage_counts_findings_and_summary_uses_the_latest_run():
    statuses = [{'rule_id': 'GEN-001', 'scope': 'GENERIC', 'title': 't', 'applicable': True, 'reason': None},
                {'rule_id': 'PLA-R010', 'scope': 'PLA', 'title': 't', 'applicable': False, 'reason': 'Not applicable: needs guys'}]
    coverage = processor.rule_coverage(statuses, [{'rule_id': 'GEN-001'}, {'rule_id': 'GEN-001'}])
    assert [c['findings'] for c in coverage] == [2, 0]
    old = SimpleNamespace(id='old', status='SUCCEEDED', finished_at=datetime(2026, 10, 1, tzinfo=timezone.utc), summary_json=json.dumps({'rules': []}))
    new = SimpleNamespace(id='new', status='SUCCEEDED', finished_at=datetime(2026, 10, 8, tzinfo=timezone.utc), summary_json=json.dumps({'rules': coverage, 'pole_sheet': 'ZoneName'}))
    failed = SimpleNamespace(id='failed', status='FAILED', finished_at=datetime(2026, 10, 9, tzinfo=timezone.utc), summary_json='{}')
    summary = rule_coverage_summary([old, new, failed])
    assert summary['qc_run_id'] == 'new' and summary['ran'] == 1 and summary['total'] == 2 and summary['pole_sheet'] == 'ZoneName'
    legacy = SimpleNamespace(id='legacy', status='SUCCEEDED', finished_at=datetime(2026, 10, 1, tzinfo=timezone.utc), summary_json=json.dumps({'findings': 3}))
    assert rule_coverage_summary([legacy]) is None and rule_coverage_summary([]) is None
