"""Sign in with an emailed one-time code, and the per-account sign-in email that receives it."""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

import pytest
from fastapi.testclient import TestClient

from app import email_login, mailer
from app import main as main_module
from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import AppSetting, AuditLog, EmailLoginCode, User
from app.network_access import POLICY_KEY

PASSWORD = "Email-Code-Test-Pass-1!"


@pytest.fixture
def outbox(monkeypatch):
    """Console-mode email with every message captured instead of logged."""
    initialize_schema()
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda to, name, subject, text, html: sent.append({"to": to, "subject": subject, "text": text}))
    email_login._REQUESTS.clear()
    main_module.LOGIN_FAILURES.clear()
    yield sent
    email_login._REQUESTS.clear()
    main_module.LOGIN_FAILURES.clear()


def account(role="USER", *, sign_in_email=None, active=True, must_change=False, remote=True):
    marker = uuid.uuid4().hex[:8]
    email = f"code-{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"C{role[:2]}{marker}", name=f"Code {marker}", role=role, password_hash=hash_password(PASSWORD),
                    sign_in_email=sign_in_email, is_active=active, must_change_password=must_change, remote_access=remote))
        db.commit()
        return email, db.query(User.id).filter_by(email=email).scalar()
    finally:
        db.close()


def real_address():
    return f"person-{uuid.uuid4().hex[:8]}@jsan-mail.com"


def code_in(message):
    return next(word for word in message["text"].split() if word.isdigit() and len(word) == 6)


def test_methods_endpoint_reports_email_codes_only_when_configured(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/auth/methods").json()["email_code"] is False
        assert client.post("/api/auth/email-code/request", json={"email": "anyone@jsan-mail.com"}).status_code == 503
        monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        assert client.get("/api/auth/methods").json()["email_code"] is False, "a half-configured provider stays off"
        monkeypatch.setenv("EMAIL_PROVIDER", "console")
        assert client.get("/api/auth/methods").json() == {"password": True, "email_code": True, "code_length": 6, "resend_seconds": 60}


def test_code_sign_in_happy_path_by_username_or_sign_in_email(outbox):
    address = real_address()
    email, user_id = account(sign_in_email=address)
    with TestClient(app) as client:
        db = SessionLocal()
        username = db.query(User.username).filter_by(id=user_id).scalar(); db.close()
        sent = client.post("/api/auth/email-code/request", json={"email": username})
        assert sent.status_code == 200 and sent.json()["message"].startswith("If an account uses this email")
        assert len(outbox) == 1 and outbox[0]["to"] == address, "the code goes to the sign-in email, not the placeholder account email"
        signed_in = client.post("/api/auth/email-code/verify", json={"email": address.upper(), "code": code_in(outbox[0])})
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["user"]["email"] == email
        token = signed_in.json()["token"]
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        # Single use.
        again = client.post("/api/auth/email-code/verify", json={"email": address, "code": code_in(outbox[0])})
        assert again.status_code == 401
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter_by(action="EMAIL_CODE_SENT", entity_id=str(user_id)).count() == 1
        assert db.query(AuditLog).filter_by(action="LOGIN_EMAIL_CODE", entity_id=str(user_id)).count() == 1
        stored = db.query(EmailLoginCode).filter_by(user_id=user_id).one()
        assert code_in(outbox[0]) not in stored.code_hash and len(stored.code_hash) == 64, "only an HMAC is stored"
    finally:
        db.close()


def test_requests_never_reveal_whether_an_account_exists(outbox):
    inactive_email, _ = account(sign_in_email=real_address(), active=False)
    placeholder_only, _ = account()  # account email is example.invalid: cannot receive mail
    with TestClient(app) as client:
        responses = [client.post("/api/auth/email-code/request", json={"email": name}).json()
                     for name in ("nobody-here@jsan-mail.com", inactive_email, placeholder_only)]
    assert all(r == responses[0] for r in responses) and responses[0]["ok"] is True
    assert outbox == [], "nothing is sent for unknown, deactivated or undeliverable accounts"


def test_wrong_codes_lock_the_code_and_expiry_is_enforced(outbox):
    address = real_address()
    _, user_id = account(sign_in_email=address)
    with TestClient(app) as client:
        client.post("/api/auth/email-code/request", json={"email": address})
        good = code_in(outbox[0])
        wrong = "000000" if good != "000000" else "111111"
        for _ in range(5):
            assert client.post("/api/auth/email-code/verify", json={"email": address, "code": wrong}).status_code == 401
        main_module.LOGIN_FAILURES.clear()
        locked = client.post("/api/auth/email-code/verify", json={"email": address, "code": good})
        assert locked.status_code == 401, "five wrong attempts spend the code"

        # A new code, then expire it.
        db = SessionLocal()
        try:
            db.query(EmailLoginCode).filter_by(user_id=user_id).update({EmailLoginCode.created_at: datetime.now(timezone.utc) - timedelta(minutes=5)})
            db.commit()
        finally:
            db.close()
        client.post("/api/auth/email-code/request", json={"email": address})
        fresh = code_in(outbox[-1])
        db = SessionLocal()
        try:
            db.query(EmailLoginCode).filter(EmailLoginCode.user_id == user_id, EmailLoginCode.used_at.is_(None)).update(
                {EmailLoginCode.expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)})
            db.commit()
        finally:
            db.close()
        assert client.post("/api/auth/email-code/verify", json={"email": address, "code": fresh}).status_code == 401


def test_resend_cooldown_and_new_code_replaces_old(outbox):
    address = real_address()
    _, user_id = account(sign_in_email=address)
    with TestClient(app) as client:
        assert client.post("/api/auth/email-code/request", json={"email": address}).status_code == 200
        too_soon = client.post("/api/auth/email-code/request", json={"email": address})
        assert too_soon.status_code == 429 and "seconds" in too_soon.json()["detail"]
        db = SessionLocal()
        try:
            db.query(EmailLoginCode).filter_by(user_id=user_id).update({EmailLoginCode.created_at: datetime.now(timezone.utc) - timedelta(minutes=2)})
            db.commit()
        finally:
            db.close()
        assert client.post("/api/auth/email-code/request", json={"email": address}).status_code == 200
        first, second = code_in(outbox[0]), code_in(outbox[1])
        if first != second:
            assert client.post("/api/auth/email-code/verify", json={"email": address, "code": first}).status_code == 401
        assert client.post("/api/auth/email-code/verify", json={"email": address, "code": second}).status_code == 200


def test_code_sign_in_keeps_network_rules_and_forced_password_change(outbox, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    office_only = real_address(); account(sign_in_email=office_only, remote=False)
    must_change = real_address(); account(sign_in_email=must_change, must_change=True)
    db = SessionLocal()
    try:
        db.add(AppSetting(key=POLICY_KEY, value_json=json.dumps({"enabled": True, "networks": [{"cidr": "52.14.20.0/24", "label": "Office"}]})))
        db.commit()
        with TestClient(app) as client:
            elsewhere = {"X-Real-IP": "34.120.5.9"}
            client.post("/api/auth/email-code/request", json={"email": office_only}, headers=elsewhere)
            assert outbox == [], "no code is sent to an office-only account from outside the office"
            client.post("/api/auth/email-code/request", json={"email": office_only}, headers={"X-Real-IP": "52.14.20.7"})
            assert len(outbox) == 1
            moved = client.post("/api/auth/email-code/verify", json={"email": office_only, "code": code_in(outbox[0])}, headers=elsewhere)
            assert moved.status_code == 403 and "office network" in moved.json()["detail"]

            client.post("/api/auth/email-code/request", json={"email": must_change}, headers={"X-Real-IP": "52.14.20.7"})
            forced = client.post("/api/auth/email-code/verify", json={"email": must_change, "code": code_in(outbox[-1])}, headers={"X-Real-IP": "52.14.20.7"})
            assert forced.status_code == 200 and forced.json()["user"]["must_change_password"] is True
            headers = {"Authorization": f"Bearer {forced.json()['token']}", "X-Real-IP": "52.14.20.7"}
            assert client.get("/api/projects", headers=headers).json()["detail"] == "password_change_required"
    finally:
        db.query(AppSetting).filter_by(key=POLICY_KEY).delete(); db.commit(); db.close()


def test_sign_in_email_is_managed_with_account_authority(outbox):
    user_email, user_id = account("USER")
    other_user, _ = account("USER", remote=True)
    admin, _ = account("ADMIN"); other_admin, other_admin_id = account("ADMIN"); boss, _ = account("SUPER_ADMIN")
    taken = real_address(); account(sign_in_email=taken)
    with TestClient(app) as client:
        def auth(email):
            r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            return {"Authorization": f"Bearer {r.json()['token']}"}
        body = {"sign_in_email": real_address()}
        assert client.put(f"/api/users/{user_id}", json=body).status_code == 401
        assert client.put(f"/api/users/{user_id}", headers=auth(other_user), json=body).status_code == 403
        a = auth(admin)
        saved = client.put(f"/api/users/{user_id}", headers=a, json=body)
        assert saved.status_code == 200 and saved.json()["sign_in_email"] == body["sign_in_email"] and saved.json()["email_code_ready"] is True
        assert saved.json()["email"] == user_email, "the account email (identity) never changes"
        assert client.put(f"/api/users/{user_id}", headers=a, json={"sign_in_email": "not-an-email"}).status_code == 422
        assert client.put(f"/api/users/{user_id}", headers=a, json={"sign_in_email": "someone@jsan.local"}).status_code == 422
        assert client.put(f"/api/users/{user_id}", headers=a, json={"sign_in_email": taken}).status_code == 409
        assert client.put(f"/api/users/{other_admin_id}", headers=a, json={"sign_in_email": real_address()}).status_code == 403
        assert client.put(f"/api/users/{other_admin_id}", headers=auth(boss), json={"sign_in_email": real_address()}).status_code == 200
        cleared = client.put(f"/api/users/{user_id}", headers=a, json={"sign_in_email": ""})
        assert cleared.json()["sign_in_email"] is None and cleared.json()["email_code_ready"] is False
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter_by(action="CHANGE_SIGN_IN_EMAIL", entity_id=str(user_id)).count() == 2
    finally:
        db.close()


def test_brevo_request_shape(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo"); monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setenv("MAIL_FROM_EMAIL", "noreply@jsan-mail.com"); monkeypatch.setenv("MAIL_FROM_NAME", "JSAN PoleGrid")
    captured = {}

    class Response:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout):
        captured.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data))
        return Response()
    monkeypatch.setattr(mailer, "urlopen", fake_urlopen)
    mailer.send_email("person@jsan-mail.com", "Person", "Subject", "text body", "<p>html</p>")
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["Api-key"] == "xkeysib-test"
    assert captured["body"] == {"sender": {"email": "noreply@jsan-mail.com", "name": "JSAN PoleGrid"}, "to": [{"email": "person@jsan-mail.com", "name": "Person"}],
                                "subject": "Subject", "textContent": "text body", "htmlContent": "<p>html</p>"}


def test_mail_failure_is_reported_and_no_code_is_kept(outbox, monkeypatch):
    address = real_address()
    _, user_id = account(sign_in_email=address)
    def broken(*args, **kwargs):
        raise mailer.MailError("Brevo rejected the email (HTTP 401)")
    monkeypatch.setattr(mailer, "send_email", broken)
    with TestClient(app) as client:
        failed = client.post("/api/auth/email-code/request", json={"email": address})
        assert failed.status_code == 503 and "password" in failed.json()["detail"]
    db = SessionLocal()
    try:
        assert db.query(EmailLoginCode).filter_by(user_id=user_id).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("settings,message", [
    ({"EMAIL_PROVIDER": "console"}, "EMAIL_PROVIDER=console"),
    ({"EMAIL_PROVIDER": "brevo"}, "BREVO_API_KEY is required"),
    ({"EMAIL_PROVIDER": "sendmail"}, "EMAIL_PROVIDER must be one of"),
])
def test_production_refuses_unsafe_mail_configuration(monkeypatch, settings, message):
    monkeypatch.setattr(main_module, "APP_ENV", "production")
    monkeypatch.setattr(main_module, "MODE", "s3")
    for key, value in {"DATABASE_URL": "postgresql://u:p@h/db", "JWT_SECRET": "x" * 40, "ADMIN_PASSWORD": "Unique-Admin-Pass-2026!",
                       "MAIL_FROM_EMAIL": "noreply@jsan-mail.com", **settings}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    with pytest.raises(RuntimeError, match=message):
        main_module.validate_runtime_environment()
