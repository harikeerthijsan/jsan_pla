import json, os
from pathlib import Path
from sqlalchemy.orm import Session
from .models import Project, Pole, LidarBlock, Finding, SceneFeature, User
from .auth import hash_password

SEED_PATH = Path(__file__).resolve().parent.parent / 'seed' / 'sample1.json'

def seed_database(db: Session):
    if db.query(Project).filter(Project.id == 'sample1').first():
        return
    data = json.loads(SEED_PATH.read_text(encoding='utf-8'))
    p = data['project']
    db.add(Project(**p))
    for b in data['blocks']:
        db.add(LidarBlock(project_id='sample1', name=b['name'], object_key=b['object_key'],
            xmin=b['xmin'],ymin=b['ymin'],xmax=b['xmax'],ymax=b['ymax'],poles_json=json.dumps(b['poles'])))
    for pole in data['poles']:
        db.add(Pole(project_id='sample1', internal_id=pole['internal_id'], pole_number=pole.get('pole_number'),
            block_name=pole.get('fbi_block'), corrected_lat=pole.get('corrected_lat'), corrected_lon=pole.get('corrected_lon'),
            bottom_elev_ft=pole.get('bottom_elev_ft'), top_elev_ft=pole.get('top_elev_ft'),
            qc_status=pole.get('qc_status') or 'PASS', qc_fail=int(pole.get('qc_fail') or 0),
            qc_review=int(pole.get('qc_review') or 0), qc_unverifiable=int(pole.get('qc_unverifiable') or 0),
            remarks=pole.get('remarks'), manifest_json=json.dumps(pole)))
    for f in data['findings']:
        db.add(Finding(id=f['id'], project_id='sample1', internal_id=f['internal_id'], pole_number=f.get('pole_number'),
            rule_id=f['rule_id'], severity=f['severity'], sheet=f['sheet'], field=f['field'], message=f['message'],
            actual=None if f.get('actual') is None else str(f.get('actual')),
            expected=None if f.get('expected') is None else str(f.get('expected')),
            related_poles_json=json.dumps(f.get('related_poles',[])), status=f.get('status','OPEN')))
    for feat in data['features']:
        iid = feat.get('properties',{}).get('internal_id')
        if iid is None: continue
        db.add(SceneFeature(project_id='sample1', internal_id=int(iid), feature_type=feat['properties'].get('feature_type','unknown'), payload_json=json.dumps(feat)))
    db.commit()

def seed_admin(db: Session):
    if db.query(User).count() > 0:
        return
    env = os.getenv('APP_ENV','development').lower()
    email = os.getenv('ADMIN_EMAIL')
    password = os.getenv('ADMIN_PASSWORD')
    if env == 'production' and (not email or not password):
        raise RuntimeError('Production requires ADMIN_EMAIL and ADMIN_PASSWORD')
    email = email or 'admin@jsan.local'
    password = password or 'ChangeMe123!'
    db.add(User(email=email, name=os.getenv('ADMIN_NAME','JSAN QC Admin'), role='ADMIN', password_hash=hash_password(password)))
    db.commit()
