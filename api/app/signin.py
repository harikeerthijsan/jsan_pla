"""What every successful sign-in must pass and record, whichever method proved the person's identity."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .models import AuditLog, User
from .network_access import client_ip, user_network_allowed


def complete_sign_in(db: Session, user: User, request: Request, method: str) -> None:
    """Refuse deactivated or off-network accounts, then record this as the latest sign-in (committed)."""
    if not user.is_active:
        raise HTTPException(403, 'This account is deactivated. Ask an admin to reactivate it.')
    ip = client_ip(request)
    if not user_network_allowed(db, user, ip):
        db.add(AuditLog(actor=user.email, action='LOGIN_BLOCKED_NETWORK', entity_type='user', entity_id=str(user.id),
                        detail_json=json.dumps({'ip': ip} if method == 'password' else {'ip': ip, 'method': method})))
        db.commit()
        raise HTTPException(403, 'This account can only be used from the office network. Ask an admin to allow access from anywhere.')
    # Only the latest sign-in is kept. The browser reports its location separately, if the person allows it.
    user.last_login_at = datetime.now(timezone.utc); user.last_login_ip = ip; user.last_login_location_status = 'pending'
    user.last_login_latitude = user.last_login_longitude = user.last_login_accuracy = None; user.last_login_location_at = None
    if method != 'password':
        db.add(AuditLog(actor=user.email, action='LOGIN_EMAIL_CODE', entity_type='user', entity_id=str(user.id), detail_json=json.dumps({'ip': ip})))
    db.commit()
