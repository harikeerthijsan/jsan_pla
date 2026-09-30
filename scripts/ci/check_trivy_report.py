"""Turn Trivy JSON findings into actionable GitHub annotations and a strict exit code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BLOCKING_SEVERITIES = {'HIGH', 'CRITICAL'}


def blocking_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for result in report.get('Results') or []:
        target = str(result.get('Target') or 'container image')
        for vulnerability in result.get('Vulnerabilities') or []:
            severity = str(vulnerability.get('Severity') or '').upper()
            fixed = str(vulnerability.get('FixedVersion') or '').strip()
            if severity not in BLOCKING_SEVERITIES or not fixed:
                continue
            findings.append({
                'target': target,
                'id': str(vulnerability.get('VulnerabilityID') or 'UNKNOWN'),
                'package': str(vulnerability.get('PkgName') or 'unknown-package'),
                'installed': str(vulnerability.get('InstalledVersion') or 'unknown'),
                'fixed': fixed,
                'severity': severity,
                'title': str(vulnerability.get('Title') or '').strip(),
            })
    return findings


def _escape(value: str) -> str:
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--source', default='.github/workflows/ci.yml')
    args = parser.parse_args(argv)

    try:
        report = json.loads(args.report.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(f'::error file={_escape(args.source)},title=Invalid Trivy report::{_escape(str(exc))}')
        return 2

    findings = blocking_findings(report)
    for finding in findings:
        title = f"{finding['severity']} {finding['id']} in {finding['package']}"
        message = (
            f"{finding['target']}: installed {finding['installed']}; fixed in {finding['fixed']}"
            + (f"; {finding['title']}" if finding['title'] else '')
        )
        print(f'::error file={_escape(args.source)},title={_escape(title)}::{_escape(message)}')

    if findings:
        print(f'Trivy gate failed: {len(findings)} fixed high/critical vulnerabilities')
        return 1
    print('Trivy gate passed: no fixed high/critical vulnerabilities')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
