"""Sign in with a one-time code sent by email (the alternative to a password).

Requesting a code always gets the same answer, so the form cannot be used to discover which addresses have
accounts. Codes are 6 digits, stored only as an HMAC, valid for 10 minutes, single use, and invalid after five
wrong attempts. A successful code sign-in goes through the same checks as a password sign-in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import mailer
from .auth import create_token
from .db import get_db
from .models import AuditLog, EmailLoginCode, User
from .network_access import client_ip, user_network_allowed
from .signin import complete_sign_in

router = APIRouter()
log = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=int(os.getenv("EMAIL_CODE_TTL_MINUTES", "10")))
MAX_ATTEMPTS = 5
RESEND_SECONDS = int(os.getenv("EMAIL_CODE_RESEND_SECONDS", "60"))
WINDOW_SECONDS = 15 * 60
MAX_PER_ADDRESS = 5
MAX_PER_IP = 20
SENT_MESSAGE = "If an account uses this email, a sign-in code is on its way. It is valid for 10 minutes."
_REQUESTS: dict[str, list[float]] = {}


class CodeRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class CodeVerifyIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=6, max_length=12)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def code_hash(user_id: int, code: str) -> str:
    secret = os.getenv("JWT_SECRET", "dev-only-change-me").encode()
    return hmac.new(secret, f"email-login:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _throttled(key: str, limit: int) -> bool:
    """Record one request for ``key``; True when the window already holds ``limit`` requests."""
    cutoff = time.time() - WINDOW_SECONDS
    hits = [t for t in _REQUESTS.get(key, []) if t >= cutoff]
    if len(hits) >= limit:
        _REQUESTS[key] = hits
        return True
    hits.append(time.time())
    _REQUESTS[key] = hits
    return False


def _find_user(db: Session, name: str) -> User | None:
    name = name.strip().lower()
    return db.query(User).filter(or_(func.lower(User.email) == name, func.lower(User.username) == name,
                                     func.lower(User.sign_in_email) == name)).first()


def delivery_address(user: User) -> str | None:
    """The sign-in email when set, otherwise the account email if it can receive mail."""
    for address in (user.sign_in_email, user.email):
        if mailer.deliverable(address):
            return address.strip().lower()
    return None


def _message(user: User, code: str) -> tuple[str, str, str]:
    minutes = int(CODE_TTL.total_seconds() // 60)
    who = user.name or user.username or user.email
    subject = f"Your JSAN PoleGrid sign-in code: {code}"
    text = (f"Hello {who},\n\nYour JSAN PoleGrid sign-in code is {code}\n\nIt is valid for {minutes} minutes and can be used once. "
            "If you did not ask for it, you can ignore this email; nobody can sign in without the code.\n")
    html = (f"<div style=\"font-family:Arial,sans-serif;color:#0f2c41;max-width:520px\"><h2 style=\"margin:0 0 12px\">JSAN PoleGrid sign-in</h2>"
            f"<p>Hello {who.replace('<', '&lt;')},</p><p>Your sign-in code is</p>"
            f"<p style=\"font-size:30px;font-weight:700;letter-spacing:6px;margin:8px 0 16px\">{code}</p>"
            f"<p>It is valid for {minutes} minutes and can be used once.</p>"
            "<p style=\"color:#5b6773;font-size:12px\">If you did not ask for this code, you can ignore this email; nobody can sign in without it.</p></div>")
    return subject, text, html


@router.get("/api/auth/methods")
def sign_in_methods():
    """Public: which sign-in tabs the login page should offer."""
    return {"password": True, "email_code": mailer.enabled(), "code_length": 6, "resend_seconds": RESEND_SECONDS}


@router.post("/api/auth/email-code/request")
def request_code(body: CodeRequestIn, request: Request, db: Session = Depends(get_db)):
    if not mailer.enabled():
        raise HTTPException(503, "Email sign-in is not available. Sign in with your password.")
    ip = client_ip(request) or (request.client.host if request.client else "unknown")
    if _throttled(f"ip|{ip}", MAX_PER_IP) or _throttled(f"addr|{body.email.strip().lower()}", MAX_PER_ADDRESS):
        raise HTTPException(429, "Too many code requests. Wait a few minutes and try again.")
    user = _find_user(db, body.email)
    # Same answer whether or not the account exists, is deactivated, has no real mailbox or is off-network.
    address = delivery_address(user) if user else None
    if not user or not user.is_active or not address or not user_network_allowed(db, user, ip):
        return {"ok": True, "message": SENT_MESSAGE, "resend_seconds": RESEND_SECONDS}
    latest = db.query(EmailLoginCode).filter_by(user_id=user.id).order_by(EmailLoginCode.id.desc()).first()
    if latest and _aware(latest.created_at) > _now() - timedelta(seconds=RESEND_SECONDS):
        wait = int(RESEND_SECONDS - (_now() - _aware(latest.created_at)).total_seconds()) + 1
        raise HTTPException(429, f"A code was sent moments ago. You can ask for a new one in {wait} seconds.")
    code = f"{secrets.randbelow(10**6):06d}"
    db.query(EmailLoginCode).filter(EmailLoginCode.user_id == user.id, EmailLoginCode.used_at.is_(None)).update(
        {EmailLoginCode.used_at: _now()}, synchronize_session=False)  # a new code replaces the previous one
    db.add(EmailLoginCode(user_id=user.id, code_hash=code_hash(user.id, code), created_at=_now(), expires_at=_now() + CODE_TTL, request_ip=ip))
    subject, text, html = _message(user, code)
    try:
        mailer.send_email(address, user.name, subject, text, html)
    except mailer.MailError as exc:
        db.rollback()
        log.error("Sign-in code email failed for user %s: %s", user.id, exc)
        raise HTTPException(503, "The sign-in email could not be sent right now. Try again shortly or sign in with your password.") from exc
    db.add(AuditLog(actor=user.email, action="EMAIL_CODE_SENT", entity_type="user", entity_id=str(user.id),
                    detail_json=json.dumps({"ip": ip, "provider": mailer.provider()})))
    db.commit()
    return {"ok": True, "message": SENT_MESSAGE, "resend_seconds": RESEND_SECONDS}


@router.post("/api/auth/email-code/verify")
def verify_code(body: CodeVerifyIn, request: Request, db: Session = Depends(get_db)):
    from .main import LOGIN_FAILURES, LOGIN_MAX_FAILURES, _login_key, _prune_login_failures, account_dict  # main includes this router

    key = _login_key(request, body.email)
    _prune_login_failures(key)
    if len(LOGIN_FAILURES.get(key, [])) >= LOGIN_MAX_FAILURES:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again later.")
    code = "".join(ch for ch in body.code if ch.isdigit())
    user = _find_user(db, body.email)
    row = (db.query(EmailLoginCode).filter(EmailLoginCode.user_id == user.id, EmailLoginCode.used_at.is_(None))
           .order_by(EmailLoginCode.id.desc()).first()) if user else None
    valid = bool(row and len(code) == 6 and _aware(row.expires_at) > _now() and row.attempts < MAX_ATTEMPTS
                 and hmac.compare_digest(row.code_hash, code_hash(user.id, code)))
    if not valid:
        LOGIN_FAILURES.setdefault(key, []).append(time.time())
        if row:
            row.attempts = (row.attempts or 0) + 1
            if row.attempts >= MAX_ATTEMPTS or _aware(row.expires_at) <= _now():
                row.used_at = _now()  # spent: ask for a new code
            db.commit()
        raise HTTPException(401, "That code is incorrect or has expired. Check the latest email or ask for a new code.")
    LOGIN_FAILURES.pop(key, None)
    row.used_at = _now()
    db.commit()
    complete_sign_in(db, user, request, "email_code")
    return {"token": create_token(user), "user": account_dict(user)}
