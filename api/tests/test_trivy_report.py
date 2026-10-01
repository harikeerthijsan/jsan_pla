import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'check_trivy_report', ROOT / 'scripts' / 'ci' / 'check_trivy_report.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_blocking_findings_include_only_fixed_high_or_critical():
    report = {
        'Results': [{
            'Target': 'image',
            'Vulnerabilities': [
                {'VulnerabilityID': 'CVE-HIGH', 'PkgName': 'a', 'PkgPath': '/env/a-1.dist-info', 'InstalledVersion': '1', 'FixedVersion': '2', 'Severity': 'HIGH'},
                {'VulnerabilityID': 'CVE-UNFIXED', 'PkgName': 'b', 'InstalledVersion': '1', 'FixedVersion': '', 'Severity': 'CRITICAL'},
                {'VulnerabilityID': 'CVE-MEDIUM', 'PkgName': 'c', 'InstalledVersion': '1', 'FixedVersion': '2', 'Severity': 'MEDIUM'},
            ],
        }],
    }

    findings = MODULE.blocking_findings(report)

    assert [finding['id'] for finding in findings] == ['CVE-HIGH']
    assert findings[0]['path'] == '/env/a-1.dist-info'


def test_main_emits_annotation_and_fails_for_blocking_finding(tmp_path, capsys):
    report = tmp_path / 'trivy.json'
    report.write_text(
        '{"Results":[{"Target":"image","Vulnerabilities":[{"VulnerabilityID":"CVE-1","PkgName":"pkg","PkgPath":"/env/pkg-1.dist-info","InstalledVersion":"1","FixedVersion":"2","Severity":"CRITICAL"}]}]}',
        encoding='utf-8',
    )

    code = MODULE.main([str(report), '--source', 'Dockerfile'])

    assert code == 1
    output = capsys.readouterr().out
    assert '::error file=Dockerfile,title=CRITICAL CVE-1 in pkg::' in output
    assert 'image (/env/pkg-1.dist-info): installed 1; fixed in 2' in output


def test_main_passes_empty_report(tmp_path, capsys):
    report = tmp_path / 'trivy.json'
    report.write_text('{"Results":[]}', encoding='utf-8')

    assert MODULE.main([str(report)]) == 0
    assert 'Trivy gate passed' in capsys.readouterr().out
