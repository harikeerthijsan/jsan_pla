import json
from pathlib import Path

def test_seed_integrity():
    p=Path(__file__).resolve().parents[1]/'seed'/'sample1.json'
    d=json.loads(p.read_text())
    assert len(d['poles'])==24
    assert len(d['findings'])==53
    assert sum(x['severity']=='FAIL' for x in d['findings'])==37
    assert sum(x['severity']=='REVIEW' for x in d['findings'])==14
    assert sum(x['severity']=='UNVERIFIABLE' for x in d['findings'])==2
    assert len([x for x in d['features'] if x['properties'].get('feature_type')=='pole'])==23
    assert next(p for p in d['poles'] if p['internal_id']==21)['fbi_block']=='pt000004'
