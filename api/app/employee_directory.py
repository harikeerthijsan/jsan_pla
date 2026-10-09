"""Employee directory: the HR export, reviewed by super admins and turned into application accounts.

Every route needs ``super.view`` (SUPER_ADMIN only). Granting access creates (or links) a ``users`` row with a
temporary password that must be changed at first sign-in. Role, active and remote-access changes on linked
accounts go through ``PUT /api/users/{id}`` so its safeguards (last admin, own account, sign-out) still apply.
Accounts are never deleted from here: work records reference them, so access is removed by deactivating.

Local loading of an HR export: ``python -m app.employee_directory import <file.csv>`` (run from ``api/``).
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import string
import sys
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import hash_password
from .db import get_db
from .models import AuditLog, EmployeeRecord, User, iso_utc
from .rbac import ROLE_PERMISSIONS, normalize_role, require_permission

router = APIRouter(prefix="/api/super/directory")
SUPER = require_permission("super.view")

GRANT_ROLES = ("USER", "ADMIN", "SUPER_ADMIN")
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_BULK = 200
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
USERNAME = re.compile(r"[A-Za-z0-9._-]+")
EMPTY = {"", "undefined", "null", "none", "n/a", "na", "-"}

# CSV header (lower-case, spaces collapsed) -> field.
COLUMNS = {
    "name": "name", "full name": "name", "employee name": "name",
    "jsan id": "jsan_id", "jsanid": "jsan_id", "username": "jsan_id",
    "employee id": "employee_id", "emp id": "employee_id", "employee code": "employee_id",
    "email": "email", "email id": "email", "email address": "email",
    "department": "department", "designation": "designation", "title": "designation",
    "date of joining": "date_of_joining", "doj": "date_of_joining", "joining date": "date_of_joining",
    "role": "source_role", "password set": "source_password_set", "last sign-in": "source_last_sign_in",
    "last sign in": "source_last_sign_in", "submission": "submission_status",
    "total years of experience": "experience_years", "experience": "experience_years", "years of experience": "experience_years",
}
TEXT_LIMITS = {"name": 255, "jsan_id": 80, "employee_id": 80, "email": 255, "department": 120, "designation": 160,
               "source_role": 40, "submission_status": 40}


def _clean(value) -> str | None:
    text = str(value if value is not None else "").strip()
    return None if text.lower() in EMPTY else text


def _date(value) -> date | None:
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{text}' (use DD-MM-YYYY)")


def _number(value) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a number") from exc
    if not 0 <= number <= 80:
        raise ValueError(f"experience {text} is out of range")
    return number


def _yes_no(value) -> bool | None:
    text = (_clean(value) or "").lower()
    return True if text in {"yes", "y", "true", "1"} else False if text in {"no", "n", "false", "0"} else None


def parse_employee_csv(content: str) -> tuple[list[dict], list[dict]]:
    """Rows ready to store, and the rows skipped with the reason (row numbers as in a spreadsheet)."""
    if len(content.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("The file is larger than 2 MB")
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
    fields = {header: COLUMNS.get(re.sub(r"\s+", " ", (header or "").strip().lower())) for header in reader.fieldnames or []}
    if "name" not in fields.values() or "email" not in fields.values():
        raise ValueError("The file needs at least Name and Email columns")
    rows, skipped, seen = [], [], set()
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise ValueError(f"The file has more than {MAX_ROWS} rows")
        record = {}
        try:
            for header, field in fields.items():
                if not field or field in record:
                    continue
                value = raw.get(header)
                if field in {"date_of_joining", "source_last_sign_in"}:
                    record[field] = _date(value)
                elif field == "experience_years":
                    record[field] = _number(value)
                elif field == "source_password_set":
                    record[field] = _yes_no(value)
                else:
                    text = _clean(value)
                    if text and len(text) > TEXT_LIMITS[field]:
                        raise ValueError(f"{field.replace('_', ' ')} is too long")
                    record[field] = text
            email = (record.get("email") or "").lower()
            if not record.get("name"):
                raise ValueError("name is missing")
            if not EMAIL.fullmatch(email):
                raise ValueError("email is missing or invalid")
            if email in seen:
                raise ValueError("email appears earlier in the file")
            if record.get("jsan_id") and not USERNAME.fullmatch(record["jsan_id"]):
                raise ValueError("JSAN ID may use only letters, numbers, dot, dash and underscore")
            record["email"] = email
            seen.add(email)
            rows.append(record)
        except ValueError as exc:
            skipped.append({"row": number, "name": _clean(raw.get(next((h for h, f in fields.items() if f == "name"), ""))) or "", "reason": str(exc)})
    return rows, skipped


def import_employees(db: Session, content: str, actor: str, source: str) -> dict:
    """Insert new employees and refresh existing ones (matched by email, then JSAN ID). Links are kept."""
    rows, skipped = parse_employee_csv(content)
    created = updated = unchanged = 0
    for record in rows:
        row = db.query(EmployeeRecord).filter(func.lower(EmployeeRecord.email) == record["email"]).first()
        if not row and record.get("jsan_id"):
            row = db.query(EmployeeRecord).filter(func.lower(EmployeeRecord.jsan_id) == record["jsan_id"].lower()).first()
            if row and row.user_id and row.email != record["email"]:
                skipped.append({"row": None, "name": record["name"], "reason": "JSAN ID belongs to an employee with access under another email"})
                continue
        clash = record.get("jsan_id") and db.query(EmployeeRecord.id).filter(
            func.lower(EmployeeRecord.jsan_id) == record["jsan_id"].lower(), EmployeeRecord.id != (row.id if row else -1)).first()
        if clash:
            skipped.append({"row": None, "name": record["name"], "reason": "JSAN ID is already used by another employee"})
            continue
        if row is None:
            db.add(EmployeeRecord(**record, source=source, updated_by=actor))
            created += 1
            continue
        changes = {key: value for key, value in record.items() if getattr(row, key) != value and not (key == "email" and row.user_id)}
        if changes:
            for key, value in changes.items():
                setattr(row, key, value)
            row.source, row.updated_by = source, actor
            updated += 1
        else:
            unchanged += 1
    summary = {"created": created, "updated": updated, "unchanged": unchanged, "skipped": skipped, "rows": len(rows) + len(skipped)}
    db.add(AuditLog(actor=actor, action="IMPORT_EMPLOYEE_DIRECTORY", entity_type="employee_directory", entity_id=source[:120],
                    detail_json=json.dumps({k: (len(v) if k == "skipped" else v) for k, v in summary.items()})))
    db.commit()
    return summary


def temporary_password() -> str:
    """Readable, strong, and always meets the 12-character minimum: Jsan-XXXXXXXXXX-NN!"""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return f"Jsan-{''.join(secrets.choice(alphabet) for _ in range(10))}-{secrets.randbelow(90) + 10}!"


def account_summary(user: User | None) -> dict | None:
    if not user:
        return None
    return {"id": user.id, "username": user.username, "email": user.email, "name": user.name, "role": normalize_role(user.role),
            "active": bool(user.is_active), "must_change_password": bool(user.must_change_password),
            "remote_access": bool(user.remote_access), "last_login_at": iso_utc(user.last_login_at)}


def employee_dict(row: EmployeeRecord, account: User | None, match: User | None = None) -> dict:
    status = "none" if not account else "inactive" if not account.is_active else "pending" if account.must_change_password else "active"
    return {
        "id": row.id, "name": row.name, "jsan_id": row.jsan_id, "employee_id": row.employee_id, "email": row.email,
        "department": row.department, "designation": row.designation,
        "date_of_joining": row.date_of_joining.isoformat() if row.date_of_joining else None,
        "experience_years": row.experience_years, "source_role": row.source_role, "source_password_set": row.source_password_set,
        "source_last_sign_in": row.source_last_sign_in.isoformat() if row.source_last_sign_in else None,
        "submission_status": row.submission_status, "access": status, "account": account_summary(account),
        "existing_account": account_summary(match) if match and not account else None,
        "updated_at": iso_utc(row.updated_at), "updated_by": row.updated_by,
    }


def _record(db: Session, record_id: int) -> EmployeeRecord:
    row = db.get(EmployeeRecord, record_id)
    if not row:
        raise HTTPException(404, "Employee not found")
    return row


def _account(db: Session, row: EmployeeRecord) -> User | None:
    return db.get(User, row.user_id) if row.user_id else None


def _unique_username(db: Session, wanted: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "", wanted)[:70] or "user"
    candidate, n = base, 1
    while db.query(User.id).filter(func.lower(User.username) == candidate.lower()).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def grant_access(db: Session, row: EmployeeRecord, role: str, remote_access: bool | None, username: str | None, actor: User) -> dict:
    """Create the application account for this employee (or link the account that already uses the email)."""
    role = role.upper()
    if role not in GRANT_ROLES or role not in ROLE_PERMISSIONS:
        raise HTTPException(400, "Unsupported role")
    if row.user_id:
        raise HTTPException(409, f"{row.name} already has access")
    existing = db.query(User).filter(func.lower(User.email) == row.email.lower()).first()
    if existing:
        if db.query(EmployeeRecord.id).filter(EmployeeRecord.user_id == existing.id).first():
            raise HTTPException(409, "That account is already linked to another employee")
        row.user_id, row.updated_by = existing.id, actor.email
        db.add(AuditLog(actor=actor.email, action="LINK_EMPLOYEE_ACCOUNT", entity_type="user", entity_id=str(existing.id),
                        detail_json=json.dumps({"employee_id": row.id, "email": existing.email, "username": existing.username})))
        return {"status": "linked", "account": existing, "temporary_password": None}
    wanted = (username or "").strip() or row.jsan_id or row.email.split("@")[0]
    if not USERNAME.fullmatch(wanted):
        raise HTTPException(422, "Username may use only letters, numbers, dot, dash and underscore")
    if username and db.query(User.id).filter(func.lower(User.username) == wanted.lower()).first():
        raise HTTPException(409, "Username already exists")
    password = temporary_password()
    account = User(email=row.email.lower(), username=_unique_username(db, wanted), name=row.name, role=role,
                   password_hash=hash_password(password), must_change_password=True,
                   remote_access=remote_access if remote_access is not None else role in {"ADMIN", "SUPER_ADMIN"})
    db.add(account)
    db.flush()
    row.user_id, row.updated_by = account.id, actor.email
    db.add(AuditLog(actor=actor.email, action="CREATE_USER", entity_type="user", entity_id=account.email,
                    detail_json=json.dumps({"role": role, "name": account.name, "source": "employee_directory", "employee_id": row.id})))
    db.add(AuditLog(actor=actor.email, action="GRANT_EMPLOYEE_ACCESS", entity_type="user", entity_id=str(account.id),
                    detail_json=json.dumps({"employee_id": row.id, "username": account.username, "email": account.email, "role": role,
                                            "remote_access": bool(account.remote_access)})))
    return {"status": "created", "account": account, "temporary_password": password}


class EmployeeIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    jsan_id: str | None = Field(default=None, max_length=80)
    employee_id: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=120)
    designation: str | None = Field(default=None, max_length=160)
    date_of_joining: date | None = None
    experience_years: float | None = Field(default=None, ge=0, le=80)


class ImportIn(BaseModel):
    filename: str = Field(default="employees.csv", max_length=255)
    csv: str = Field(min_length=1, max_length=MAX_CSV_BYTES)


class GrantIn(BaseModel):
    role: str = "USER"
    remote_access: bool | None = None
    username: str | None = Field(default=None, max_length=80)


class BulkGrantIn(GrantIn):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK)


def _apply(db: Session, row: EmployeeRecord | None, body: EmployeeIn) -> dict:
    email = body.email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(422, "Enter a valid email address")
    jsan_id = (body.jsan_id or "").strip() or None
    if jsan_id and not USERNAME.fullmatch(jsan_id):
        raise HTTPException(422, "JSAN ID may use only letters, numbers, dot, dash and underscore")
    me = row.id if row else -1
    if db.query(EmployeeRecord.id).filter(func.lower(EmployeeRecord.email) == email, EmployeeRecord.id != me).first():
        raise HTTPException(409, "Another employee already uses that email")
    if jsan_id and db.query(EmployeeRecord.id).filter(func.lower(EmployeeRecord.jsan_id) == jsan_id.lower(), EmployeeRecord.id != me).first():
        raise HTTPException(409, "Another employee already uses that JSAN ID")
    if row and row.user_id and email != row.email.lower():
        raise HTTPException(409, "The email can't change once the employee has an account (it identifies their work)")
    return {"name": body.name.strip(), "email": email, "jsan_id": jsan_id,
            "employee_id": (body.employee_id or "").strip() or None, "department": (body.department or "").strip() or None,
            "designation": (body.designation or "").strip() or None, "date_of_joining": body.date_of_joining,
            "experience_years": body.experience_years}


@router.get("")
def list_directory(u: User = Depends(SUPER), db: Session = Depends(get_db)):
    rows = db.query(EmployeeRecord).order_by(EmployeeRecord.name).all()
    accounts = {a.id: a for a in db.query(User).filter(User.id.in_([r.user_id for r in rows if r.user_id])).all()} if rows else {}
    emails = {a.email.lower(): a for a in db.query(User).filter(func.lower(User.email).in_([r.email.lower() for r in rows if not r.user_id])).all()} if rows else {}
    out = [employee_dict(r, accounts.get(r.user_id), emails.get(r.email.lower())) for r in rows]
    facet = lambda key: sorted({e[key] for e in out if e[key]}, key=str.lower)
    return {"employees": out, "facets": {"department": facet("department"), "designation": facet("designation"), "source_role": facet("source_role")},
            "totals": {status: sum(e["access"] == status for e in out) for status in ("none", "active", "pending", "inactive")} | {"all": len(out)}}


@router.post("/import")
def import_directory(body: ImportIn, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    if not body.filename.lower().endswith(".csv"):
        raise HTTPException(422, "Choose a .csv file")
    try:
        return import_employees(db, body.csv, u.email, body.filename)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("")
def create_employee(body: EmployeeIn, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    row = EmployeeRecord(**_apply(db, None, body), source="manual", updated_by=u.email)
    db.add(row)
    db.flush()
    db.add(AuditLog(actor=u.email, action="CREATE_EMPLOYEE", entity_type="employee_directory", entity_id=str(row.id),
                    detail_json=json.dumps({"name": row.name, "email": row.email})))
    db.commit()
    return employee_dict(row, None)


@router.put("/{record_id}")
def update_employee(record_id: int, body: EmployeeIn, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    row = _record(db, record_id)
    values = _apply(db, row, body)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = u.email
    account = _account(db, row)
    # The application account keeps the employee's current name.
    if account and account.name != row.name:
        account.name = row.name
    db.add(AuditLog(actor=u.email, action="UPDATE_EMPLOYEE", entity_type="employee_directory", entity_id=str(row.id),
                    detail_json=json.dumps({"name": row.name, "email": row.email, "account_id": row.user_id})))
    db.commit()
    return employee_dict(row, account)


@router.delete("/{record_id}")
def delete_employee(record_id: int, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    row = _record(db, record_id)
    account = _account(db, row)
    if account and account.is_active:
        raise HTTPException(409, f"{row.name} still has access. Deactivate their account first; it is kept for their work history.")
    db.add(AuditLog(actor=u.email, action="DELETE_EMPLOYEE", entity_type="employee_directory", entity_id=str(row.id),
                    detail_json=json.dumps({"name": row.name, "email": row.email, "account_id": row.user_id})))
    db.delete(row)
    db.commit()
    return {"deleted": record_id}


@router.post("/grant")
def bulk_grant(body: BulkGrantIn, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    results = []
    for record_id in dict.fromkeys(body.ids):
        row = db.get(EmployeeRecord, record_id)
        if not row:
            results.append({"id": record_id, "status": "error", "error": "Employee not found"})
            continue
        try:
            # grant_access checks everything before it changes anything, so a refused row leaves no trace.
            granted = grant_access(db, row, body.role, body.remote_access, None, u)
            results.append({"id": row.id, "name": row.name, "email": row.email, "status": granted["status"],
                            "username": granted["account"].username, "role": normalize_role(granted["account"].role),
                            "temporary_password": granted["temporary_password"]})
        except HTTPException as exc:
            results.append({"id": row.id, "name": row.name, "email": row.email, "status": "error", "error": exc.detail})
    db.commit()
    return {"results": results, "granted": sum(r["status"] in {"created", "linked"} for r in results)}


@router.post("/{record_id}/grant")
def grant(record_id: int, body: GrantIn, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    row = _record(db, record_id)
    granted = grant_access(db, row, body.role, body.remote_access, body.username, u)
    db.commit()
    return {"status": granted["status"], "temporary_password": granted["temporary_password"], "employee": employee_dict(row, granted["account"])}


@router.post("/{record_id}/reset-password")
def reset_password(record_id: int, u: User = Depends(SUPER), db: Session = Depends(get_db)):
    row = _record(db, record_id)
    account = _account(db, row)
    if not account:
        raise HTTPException(409, f"{row.name} has no account yet")
    if account.id == u.id:
        raise HTTPException(409, "Change your own password from your profile")
    password = temporary_password()
    account.password_hash = hash_password(password)
    account.must_change_password = True
    account.token_version = (account.token_version or 0) + 1
    db.add(AuditLog(actor=u.email, action="RESET_PASSWORD", entity_type="user", entity_id=str(account.id),
                    detail_json=json.dumps({"username": account.username, "email": account.email, "source": "employee_directory"})))
    db.commit()
    return {"temporary_password": password, "employee": employee_dict(row, account)}


def _cli(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "import":
        print("usage: python -m app.employee_directory import <file.csv>", file=sys.stderr)
        return 2
    from pathlib import Path

    from .db import SessionLocal, initialize_schema

    path = Path(argv[1])
    initialize_schema()
    db = SessionLocal()
    try:
        summary = import_employees(db, path.read_text(encoding="utf-8-sig"), "local-maintenance", path.name)
    finally:
        db.close()
    print(f"{summary['rows']} rows: {summary['created']} added, {summary['updated']} updated, "
          f"{summary['unchanged']} unchanged, {len(summary['skipped'])} skipped")
    for item in summary["skipped"][:20]:
        print(f"  skipped row {item['row']}: {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
