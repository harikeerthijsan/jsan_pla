"""Validate and compare auditable PLA profile-parity evidence.

No acceptance thresholds are embedded here. Comparison is permitted only when
the evidence names the Delivery/customer tolerance source and supplies explicit
numeric tolerances.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SUMMARY_GROUPS = ('station', 'offset', 'elevation')
SUMMARY_FIELDS = ('min', 'max')


def _mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_evidence(evidence: dict[str, Any], require_tolerances: bool = False) -> list[str]:
    errors: list[str] = []
    for field in ('schema_version', 'dataset', 'span', 'corridor', 'workbench', 'reference', 'review'):
        if field not in evidence:
            errors.append(f'missing {field}')

    dataset = evidence.get('dataset', {})
    if not _mapping(dataset):
        errors.append('dataset must be an object')
    else:
        for field in ('project_id', 'version', 'crs', 'units'):
            if not str(dataset.get(field, '')).strip():
                errors.append(f'missing dataset.{field}')

    span = evidence.get('span', {})
    if not _mapping(span):
        errors.append('span must be an object')
    else:
        for field in ('primary_pole', 'target_pole'):
            if not str(span.get(field, '')).strip():
                errors.append(f'missing span.{field}')

    corridor = evidence.get('corridor', {})
    if not _mapping(corridor):
        errors.append('corridor must be an object')
    else:
        for field in ('width', 'depth', 'resolution', 'cross_station'):
            value = corridor.get(field)
            if not _number(value):
                errors.append(f'corridor.{field} must be numeric')
            elif field != 'cross_station' and value <= 0:
                errors.append(f'corridor.{field} must be greater than zero')

    for source_name in ('workbench', 'reference'):
        source = evidence.get(source_name, {})
        if not _mapping(source):
            errors.append(f'{source_name} must be an object')
            continue
        metrics = source.get('metrics', {})
        if not _mapping(metrics):
            errors.append(f'{source_name}.metrics must be an object')
            continue
        point_count = metrics.get('point_count')
        if not isinstance(point_count, int) or isinstance(point_count, bool) or point_count < 0:
            errors.append(f'{source_name}.metrics.point_count must be a non-negative integer')
        for group in SUMMARY_GROUPS:
            values = metrics.get(group, {})
            if not _mapping(values):
                errors.append(f'{source_name}.metrics.{group} must be an object')
                continue
            for field in SUMMARY_FIELDS:
                if not _number(values.get(field)):
                    errors.append(f'{source_name}.metrics.{group}.{field} must be numeric')
        stations = metrics.get('pole_stations', {})
        if not _mapping(stations):
            errors.append(f'{source_name}.metrics.pole_stations must be an object')
        else:
            for field in ('primary', 'target'):
                if not _number(stations.get(field)):
                    errors.append(f'{source_name}.metrics.pole_stations.{field} must be numeric')

    reference = evidence.get('reference', {})
    if _mapping(reference) and not str(reference.get('system', '')).strip():
        errors.append('missing reference.system')

    review = evidence.get('review', {})
    if not _mapping(review):
        errors.append('review must be an object')
    else:
        for field in ('reviewer', 'date'):
            if not str(review.get(field, '')).strip():
                errors.append(f'missing review.{field}')

    tolerances = evidence.get('tolerances')
    if require_tolerances or tolerances is not None:
        if not _mapping(tolerances):
            errors.append('tolerances must be an object before comparison')
        else:
            if not str(tolerances.get('source', '')).strip():
                errors.append('missing tolerances.source')
            for field in ('point_count', *SUMMARY_GROUPS):
                value = tolerances.get(field)
                if not _number(value) or value < 0:
                    errors.append(f'tolerances.{field} must be a non-negative number')

    return errors


def compare_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    errors = validate_evidence(evidence, require_tolerances=True)
    if errors:
        raise ValueError('; '.join(errors))

    observed = evidence['workbench']['metrics']
    reference = evidence['reference']['metrics']
    tolerances = evidence['tolerances']
    comparisons: list[dict[str, Any]] = []

    def add(metric: str, actual: float, expected: float, tolerance_name: str) -> None:
        difference = abs(actual - expected)
        tolerance = tolerances[tolerance_name]
        comparisons.append({
            'metric': metric,
            'workbench': actual,
            'reference': expected,
            'absolute_difference': difference,
            'tolerance': tolerance,
            'passed': difference <= tolerance,
        })

    add('point_count', observed['point_count'], reference['point_count'], 'point_count')
    for group in SUMMARY_GROUPS:
        for field in SUMMARY_FIELDS:
            add(f'{group}.{field}', observed[group][field], reference[group][field], group)
    for field in ('primary', 'target'):
        add(
            f'pole_stations.{field}',
            observed['pole_stations'][field],
            reference['pole_stations'][field],
            'station',
        )

    return {
        'status': 'PASS' if all(row['passed'] for row in comparisons) else 'FAIL',
        'tolerance_source': tolerances['source'],
        'comparisons': comparisons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'compare'))
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = json.loads(args.evidence.read_text(encoding='utf-8'))
        if not isinstance(evidence, dict):
            raise ValueError('evidence root must be an object')
        if args.action == 'validate':
            errors = validate_evidence(evidence)
            if errors:
                raise ValueError('; '.join(errors))
            result = {'status': 'VALID', 'comparison_ready': not validate_evidence(evidence, True)}
        else:
            result = compare_evidence(evidence)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'status': 'INVALID', 'error': str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] != 'FAIL' else 1


if __name__ == '__main__':
    raise SystemExit(main())
