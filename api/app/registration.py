"""Self-registration for employees: an email in the employee directory, without an account yet, becomes a User account.

Only the USER role can be created here; admins and super admins are still created by a super admin. Being listed in the
directory is the only check (by decision, see .agent/plans/2026-10-19-self-registration.md), so registration never touches
an existing account, the role is fixed, attempts are throttled and every registration is audited.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import throttle
from .auth import hash_password
from .db import get_db
from .employee_directory import USERNAME, _unique_username
from .models import AuditLog, EmployeeRecord, User
from .network_access import client_ip

router = APIRouter()

WINDOW_SECONDS = 15 * 60
MAX_PER_IP = 30
MAX_PER_ADDRESS = 10
NOT_LISTED = "This email isn't in the employee directory. Ask your administrator to add you, then register again."
ALREADY = "An account already exists for this email. Sign in instead, or ask an admin if you can't."


class RegisterCheckIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class RegisterIn(RegisterCheckIn):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=256)


def _throttle(request: Request, email: str) -> None:
    ip = client_ip(request) or (request.client.host if request.client else "unknown")
    if (throttle.check_and_record(f"register|ip|{ip}", MAX_PER_IP, WINDOW_SECONDS)
            or throttle.check_and_record(f"register|addr|{email}", MAX_PER_ADDRESS, WINDOW_SECONDS)):
        raise HTTPException(429, "Too many registration attempts. Wait a few minutes and try again.")


def _eligible(db: Session, email: str) -> EmployeeRecord:
    """The directory row for this email, if it can register: listed, and no account uses the email yet."""
    row = db.query(EmployeeRecord).filter(func.lower(EmployeeRecord.email) == email).first()
    if not row:
        raise HTTPException(404, NOT_LISTED)
    # Any account already using this address, as its account email or as its separate sign-in email, blocks registration:
    # it must never create a second account for a person who already has one, or touch an existing account.
    taken = db.query(User.id).filter(or_(func.lower(User.email) == email, func.lower(User.sign_in_email) == email)).first()
    if row.user_id or taken:
        raise HTTPException(409, ALREADY)
    return row


def _suggested_username(db: Session, row: EmployeeRecord) -> str:
    return _unique_username(db, row.jsan_id or row.email.split("@")[0])


@router.post("/api/auth/register/check")
def register_check(body: RegisterCheckIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    _throttle(request, email)
    row = _eligible(db, email)
    return {"name": row.name, "jsan_id": row.jsan_id, "email": row.email, "suggested_username": _suggested_username(db, row)}


@router.post("/api/auth/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    _throttle(request, email)
    row = _eligible(db, email)
    username = body.username.strip()
    if not USERNAME.fullmatch(username):
        raise HTTPException(422, "Username may use only letters, numbers, dot, dash and underscore")
    if db.query(User.id).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(409, f"Username {username} is already taken. Choose another.")
    if body.password.strip().lower() in {username.lower(), email} or re.fullmatch(r"(.)\1+", body.password):
        raise HTTPException(422, "Choose a password that isn't your username, your email or one repeated character")
    account = User(email=email, username=username, name=row.name, role="USER", password_hash=hash_password(body.password),
                   must_change_password=False, remote_access=False)
    db.add(account)
    db.flush()
    row.user_id, row.updated_by = account.id, email
    ip = client_ip(request) or (request.client.host if request.client else None)
    db.add(AuditLog(actor=email, action="SELF_REGISTER", entity_type="user", entity_id=str(account.id),
                    detail_json=json.dumps({"email": email, "username": username, "employee_id": row.id, "role": "USER", "ip": ip})))
    db.commit()
    return {"ok": True, "username": account.username, "name": account.name,
            "message": "Your account is ready. Sign in with your username or email and the password you chose."}
