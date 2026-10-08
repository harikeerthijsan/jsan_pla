import json, os
from pathlib import Path
from sqlalchemy.orm import Session
from .models import Project, Pole, LidarBlock, Finding, SceneFeature, User, AuditLog
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
            x_min=b['xmin'],y_min=b['ymin'],x_max=b['xmax'],y_max=b['ymax'],poles_json=json.dumps(b['poles'])))
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

STAFF_ACCOUNTS = [('Admin001', 'ADMIN'), ('Admin002', 'ADMIN')] + [(f'JSAN{n:03d}', 'USER') for n in range(1, 21)]
STAFF_EMAIL_DOMAIN = 'polegrid.jsan.local'


def staff_email(username: str) -> str:
    return f'{username.lower()}@{STAFF_EMAIL_DOMAIN}'


def seed_staff_accounts(db: Session) -> list[str]:
    """Create any missing staff account with the shared STAFF_INITIAL_PASSWORD.

    Runs on every start so a fresh production database gets the accounts on deploy. Existing
    accounts are never touched, so a password a person has already changed is kept. Everyone
    must replace the shared password at first sign-in.
    """
    password = os.getenv('STAFF_INITIAL_PASSWORD', '')
    if not password:
        return []
    existing = {name.lower() for (name,) in db.query(User.username).filter(User.username.isnot(None)).all()}
    created = []
    for username, role in STAFF_ACCOUNTS:
        if username.lower() in existing or db.query(User.id).filter(User.email == staff_email(username)).first():
            continue
        db.add(User(email=staff_email(username), username=username, name=username, role=role,
                    password_hash=hash_password(password), must_change_password=True, remote_access=role == 'ADMIN'))
        db.add(AuditLog(actor='system', action='SEED_STAFF_ACCOUNT', entity_type='user', entity_id=username,
                        detail_json=json.dumps({'role': role})))
        created.append(username)
    db.commit()
    return created


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
    db.add(User(email=email, name=os.getenv('ADMIN_NAME','JSAN QC Admin'), role='ADMIN', password_hash=hash_password(password), remote_access=True))
    db.commit()


def promote_super_admins(db: Session) -> list[str]:
    """Promote the accounts named in SUPER_ADMIN_EMAILS (e-mails or usernames, comma separated) to SUPER_ADMIN.

    This server setting is the only way to create the first super admin: nobody can grant it to themselves in the
    app. Accounts already promoted, or not found, are left alone; each promotion is audited."""
    wanted = {item.strip().lower() for item in os.getenv('SUPER_ADMIN_EMAILS', '').split(',') if item.strip()}
    promoted = []
    for user in db.query(User).all() if wanted else []:
        keys = {(user.email or '').lower(), (user.username or '').lower()}
        if keys & wanted and (user.role or '').upper() != 'SUPER_ADMIN':
            previous = user.role
            user.role = 'SUPER_ADMIN'
            db.add(AuditLog(actor='system', action='PROMOTE_SUPER_ADMIN', entity_type='user', entity_id=str(user.id),
                            detail_json=json.dumps({'username': user.username, 'email': user.email, 'previous_role': previous,
                                                    'source': 'SUPER_ADMIN_EMAILS'})))
            promoted.append(user.username or user.email)
    if promoted: db.commit()
    return promoted
