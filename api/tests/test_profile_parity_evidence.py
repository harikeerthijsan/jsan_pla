import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'profile_parity_evidence', ROOT / 'scripts' / 'profile_parity_evidence.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def evidence():
    metrics = {
        'point_count': 1000,
        'station': {'min': 0.0, 'max': 100.0},
        'offset': {'min': -6.0, 'max': 6.0},
        'elevation': {'min': 500.0, 'max': 550.0},
        'pole_stations': {'primary': 0.0, 'target': 100.0},
    }
    return {
        'schema_version': 1,
        'dataset': {'project_id': 'synthetic', 'version': 'v1', 'crs': 'EPSG:6424', 'units': 'US survey foot'},
        'span': {'primary_pole': 'P1', 'target_pole': 'P2'},
        'corridor': {'width': 12.0, 'depth': 12.0, 'resolution': 0.5, 'cross_station': 50.0},
        'workbench': {'metrics': {key: (value.copy() if isinstance(value, dict) else value) for key, value in metrics.items()}},
        'reference': {'system': 'synthetic-test-reference', 'metrics': metrics},
        'review': {'reviewer': 'automated-test', 'date': '2026-09-30'},
        'tolerances': {'source': 'synthetic test only', 'point_count': 0, 'station': 0.01, 'offset': 0.01, 'elevation': 0.01},
    }


def test_evidence_requires_traceable_dataset_and_span():
    sample = evidence()
    sample['dataset']['crs'] = ''
    sample['span']['target_pole'] = ''

    errors = MODULE.validate_evidence(sample)

    assert 'missing dataset.crs' in errors
    assert 'missing span.target_pole' in errors


def test_comparison_requires_approved_tolerance_source():
    sample = evidence()
    sample['tolerances'] = None

    with pytest.raises(ValueError, match='tolerances must be an object'):
        MODULE.compare_evidence(sample)


def test_comparison_passes_within_supplied_tolerances():
    sample = evidence()
    sample['workbench']['metrics']['elevation']['max'] = 550.005

    result = MODULE.compare_evidence(sample)

    assert result['status'] == 'PASS'
    assert result['tolerance_source'] == 'synthetic test only'


def test_comparison_reports_each_out_of_tolerance_metric():
    sample = evidence()
    sample['workbench']['metrics']['point_count'] = 999
    sample['workbench']['metrics']['offset']['max'] = 6.5

    result = MODULE.compare_evidence(sample)

    assert result['status'] == 'FAIL'
    failed = {row['metric'] for row in result['comparisons'] if not row['passed']}
    assert failed == {'point_count', 'offset.max'}
