"""Employee directory: super-admin only; CSV import; granting access creates a linked account that can sign in."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.employee_directory import parse_employee_csv, temporary_password
from app.main import app
from app.models import AuditLog, EmployeeRecord, User

PASSWORD = "Directory-Test-Pass-1!"
HEADER = "﻿Name,JSAN ID,Employee ID,Email,Department,Designation,Date of joining,Role,Password set,Last sign-in,Submission,Total years of experience\n"


def _account(role):
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    email = f"dir-{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"DIR{role[:2]}{marker}", name=f"{role.title()} {marker}", role=role,
                    password_hash=hash_password(PASSWORD), remote_access=True))
        db.commit()
        return email
    finally:
        db.close()


def _auth(client, email, password=PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _csv(*people):
    return HEADER + "".join(people)


def _person(marker, n, **over):
    values = {"name": f"Person {marker}{n}", "jsan": f"p{marker}{n}", "emp": "undefined", "email": f"p{marker}{n}@jsan-test.com",
              "dept": "Engineering", "desig": "GIS Developer", "doj": "27-05-2026", "role": "employee", "pw": "No", "last": "",
              "sub": "draft", "exp": "2"} | over
    return ",".join(values[k] for k in ("name", "jsan", "emp", "email", "dept", "desig", "doj", "role", "pw", "last", "sub", "exp")) + "\n"


@pytest.fixture
def boss():
    return _account("SUPER_ADMIN")


def test_directory_routes_need_a_super_admin():
    user, admin = _account("USER"), _account("ADMIN")
    routes = [("get", "/api/super/directory", None), ("post", "/api/super/directory/import", {"filename": "a.csv", "csv": "Name,Email\n"}),
              ("post", "/api/super/directory", {"name": "Someone", "email": "someone@jsan-test.com"}),
              ("put", "/api/super/directory/1", {"name": "Someone", "email": "someone@jsan-test.com"}),
              ("delete", "/api/super/directory/1", None), ("post", "/api/super/directory/1/grant", {"role": "USER"}),
              ("post", "/api/super/directory/grant", {"ids": [1], "role": "USER"}), ("post", "/api/super/directory/1/reset-password", None)]
    with TestClient(app) as client:
        for method, route, body in routes:
            kwargs = {"json": body} if body is not None else {}
            assert getattr(client, method)(route, **kwargs).status_code == 401, route
            for who in (user, admin):
                assert getattr(client, method)(route, headers=_auth(client, who), **kwargs).status_code == 403, (route, who)


def test_parse_handles_the_hr_export_shape():
    rows, skipped = parse_employee_csv(_csv(
        _person("x", 1),
        _person("x", 2, emp="JSAN309", doj="", exp="", pw="Yes", last="06-10-2026", role="superadmin"),
        _person("x", 3, email="not-an-email"),
        _person("x", 4, doj="31-31-2026"),
        _person("x", 5, email="PX1@jsan-test.com"),
    ))
    assert [r["email"] for r in rows] == ["px1@jsan-test.com", "px2@jsan-test.com"]
    first, second = rows
    assert first["employee_id"] is None and first["date_of_joining"] == date(2026, 5, 27) and first["experience_years"] == 2
    assert second["employee_id"] == "JSAN309" and second["source_password_set"] is True and second["source_last_sign_in"] == date(2026, 10, 6)
    assert second["source_role"] == "superadmin" and second["date_of_joining"] is None
    assert [s["row"] for s in skipped] == [4, 5, 6]
    with pytest.raises(ValueError):
        parse_employee_csv("Department,Designation\nIT,Manager\n")


def test_temporary_passwords_are_strong_and_unique():
    passwords = {temporary_password() for _ in range(50)}
    assert len(passwords) == 50 and all(len(p) >= 12 and p.startswith("Jsan-") for p in passwords)


def test_import_upserts_and_lists_with_facets(boss):
    marker = uuid.uuid4().hex[:6]
    with TestClient(app) as client:
        headers = _auth(client, boss)
        first = client.post("/api/super/directory/import", headers=headers, json={"filename": "hr.csv", "csv": _csv(_person(marker, 1), _person(marker, 2))})
        assert first.status_code == 200 and first.json()["created"] == 2, first.text
        again = client.post("/api/super/directory/import", headers=headers,
                            json={"filename": "hr.csv", "csv": _csv(_person(marker, 1, desig="Manager"), _person(marker, 2))})
        assert (again.json()["created"], again.json()["updated"], again.json()["unchanged"]) == (0, 1, 1)
        assert client.post("/api/super/directory/import", headers=headers, json={"filename": "hr.txt", "csv": "x"}).status_code == 422
        listing = client.get("/api/super/directory", headers=headers).json()
        mine = {e["email"]: e for e in listing["employees"] if marker in e["email"]}
        assert mine[f"p{marker}1@jsan-test.com"]["designation"] == "Manager" and mine[f"p{marker}1@jsan-test.com"]["access"] == "none"
        assert "Engineering" in listing["facets"]["department"] and listing["totals"]["all"] >= 2


def test_grant_creates_a_linked_account_that_must_change_its_password(boss):
    marker = uuid.uuid4().hex[:6]
    with TestClient(app) as client:
        headers = _auth(client, boss)
        client.post("/api/super/directory/import", headers=headers, json={"filename": "hr.csv", "csv": _csv(_person(marker, 1))})
        employee = next(e for e in client.get("/api/super/directory", headers=headers).json()["employees"] if e["jsan_id"] == f"p{marker}1")
        granted = client.post(f"/api/super/directory/{employee['id']}/grant", headers=headers, json={"role": "SUPER_ADMIN"})
        assert granted.status_code == 200, granted.text
        body = granted.json()
        assert body["status"] == "created" and body["employee"]["access"] == "pending"
        assert body["employee"]["account"]["username"] == f"p{marker}1" and body["employee"]["account"]["role"] == "SUPER_ADMIN"
        assert body["employee"]["account"]["remote_access"] is True
        # The new person signs in with the temporary password and is asked to change it.
        login = client.post("/api/auth/login", json={"email": f"p{marker}1", "password": body["temporary_password"]})
        assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True
        assert client.post(f"/api/super/directory/{employee['id']}/grant", headers=headers, json={"role": "USER"}).status_code == 409
        # Reset issues a new password and ends existing sign-ins.
        token = {"Authorization": f"Bearer {login.json()['token']}"}
        reset = client.post(f"/api/super/directory/{employee['id']}/reset-password", headers=headers)
        assert reset.status_code == 200 and reset.json()["temporary_password"] != body["temporary_password"]
        assert client.get("/api/auth/me", headers=token).status_code == 401
        assert client.post("/api/auth/login", json={"email": f"p{marker}1", "password": reset.json()["temporary_password"]}).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter_by(action="GRANT_EMPLOYEE_ACCESS", actor=boss).count() >= 1
    finally:
        db.close()


def test_bulk_grant_reports_each_person_and_links_existing_accounts(boss):
    marker = uuid.uuid4().hex[:6]
    existing = _account("USER")
    with TestClient(app) as client:
        headers = _auth(client, boss)
        client.post("/api/super/directory/import", headers=headers,
                    json={"filename": "hr.csv", "csv": _csv(_person(marker, 1), _person(marker, 2), _person(marker, 3, email=existing, jsan=f"e{marker}"))})
        ids = {e["email"]: e["id"] for e in client.get("/api/super/directory", headers=headers).json()["employees"] if marker in (e["jsan_id"] or "")}
        listed = next(e for e in client.get("/api/super/directory", headers=headers).json()["employees"] if e["email"] == existing)
        assert listed["existing_account"]["email"] == existing
        result = client.post("/api/super/directory/grant", headers=headers, json={"ids": [*ids.values(), 999999], "role": "USER"})
        assert result.status_code == 200, result.text
        by_status = {}
        for item in result.json()["results"]:
            by_status.setdefault(item["status"], []).append(item)
        assert len(by_status["created"]) == 2 and all(i["temporary_password"] for i in by_status["created"])
        assert [i["email"] for i in by_status["linked"]] == [existing] and by_status["linked"][0]["temporary_password"] is None
        assert by_status["error"][0]["error"] == "Employee not found"
    db = SessionLocal()
    try:
        assert db.query(User).filter_by(email=existing).count() == 1
    finally:
        db.close()


def test_edit_syncs_the_account_and_delete_needs_access_removed_first(boss):
    marker = uuid.uuid4().hex[:6]
    with TestClient(app) as client:
        headers = _auth(client, boss)
        created = client.post("/api/super/directory", headers=headers, json={"name": "Manual Person", "email": f"m{marker}@jsan-test.com", "jsan_id": f"m{marker}"})
        assert created.status_code == 200, created.text
        record = created.json()["id"]
        assert client.post("/api/super/directory", headers=headers, json={"name": "Twin", "email": f"m{marker}@jsan-test.com"}).status_code == 409
        account = client.post(f"/api/super/directory/{record}/grant", headers=headers, json={"role": "ADMIN", "remote_access": False}).json()["employee"]["account"]
        assert account["role"] == "ADMIN" and account["remote_access"] is False
        renamed = client.put(f"/api/super/directory/{record}", headers=headers, json={"name": "Renamed Person", "email": f"m{marker}@jsan-test.com", "jsan_id": f"m{marker}"})
        assert renamed.status_code == 200 and renamed.json()["account"]["name"] == "Renamed Person"
        assert client.put(f"/api/super/directory/{record}", headers=headers, json={"name": "Renamed Person", "email": f"other{marker}@jsan-test.com"}).status_code == 409
        assert client.delete(f"/api/super/directory/{record}", headers=headers).status_code == 409
        # Removing access goes through the normal account route; then the entry can be deleted and the account is kept.
        assert client.put(f"/api/users/{account['id']}", headers=headers, json={"active": False}).status_code == 200
        assert client.delete(f"/api/super/directory/{record}", headers=headers).status_code == 200
        assert client.get("/api/super/directory", headers=headers).json()["employees"] == [
            e for e in client.get("/api/super/directory", headers=headers).json()["employees"] if e["id"] != record]
    db = SessionLocal()
    try:
        assert db.get(EmployeeRecord, record) is None and db.get(User, account["id"]).is_active is False
    finally:
        db.close()
