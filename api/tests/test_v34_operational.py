import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Finding, ProcessingJob, Project
from app.workflow import DatasetVersion, ProcessingLease, claim_next_job, finish_job_lease


def _login(client, email="admin@jsan.local", password="ChangeMe123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _create_user(client, headers, role):
    marker = uuid.uuid4().hex[:8]
    email = f"{role.lower()}-{marker}@example.invalid"
    password = "Unique-Test-Password-123!"
    r = client.post(
        "/api/users",
        headers=headers,
        json={"email": email, "name": f"{role} Test", "role": role, "password": password},
    )
    assert r.status_code == 200, r.text
    return email, password


def test_v34_runtime_identity_and_named_role_workspaces():
    with TestClient(app) as client:
        admin = _login(client)
        info = client.get("/api/system/info").json()
        assert info["version"].startswith("3.4.")
        assert info["service"] == "pla-qc"

        delivery_email, delivery_pw = _create_user(client, admin, "DELIVERY_USER")
        qc_email, qc_pw = _create_user(client, admin, "QC_REVIEWER")

        delivery = _login(client, delivery_email, delivery_pw)
        qc = _login(client, qc_email, qc_pw)

        dw = client.get("/api/workspaces", headers=delivery)
        assert dw.status_code == 200
        assert dw.json()["workspaces"] == ["DELIVERY"]
        assert "upload.create" in dw.json()["permissions"]

        qw = client.get("/api/workspaces", headers=qc)
        assert qw.status_code == 200
        assert qw.json()["workspaces"] == ["QC"]
        assert "finding.review" in qw.json()["permissions"]

        # UI hiding is not authorization: Delivery users cannot create programs and
        # QC reviewers cannot mutate Delivery project setup.
        assert client.post("/api/projects", headers=delivery, json={"name": "Denied Delivery Create"}).status_code == 403
        assert client.post("/api/projects", headers=qc, json={"name": "Denied QC Create"}).status_code == 403


def test_dataset_version_and_correction_lifecycle():
    with TestClient(app) as client:
        admin = _login(client)
        marker = uuid.uuid4().hex[:8]
        pr = client.post(
            "/api/projects",
            headers=admin,
            json={"name": f"Workflow {marker}", "customer": "PLA", "crs": "EPSG:6424", "units": "US survey foot"},
        )
        assert pr.status_code == 200, pr.text
        project_id = pr.json()["id"]

        workflow = client.get(f"/api/projects/{project_id}/workflow", headers=admin)
        assert workflow.status_code == 200
        v1 = workflow.json()["current_version"]
        assert v1["version_no"] == 1
        assert v1["status"] == "UPLOADING"

        # Once QC has completed, Delivery can open a new immutable source revision.
        db = SessionLocal()
        try:
            row = db.query(DatasetVersion).filter_by(id=v1["id"]).first()
            row.status = "READY_FOR_QC"
            project = db.query(Project).filter_by(id=project_id).first()
            project.status = "READY_FOR_QC"
            finding = Finding(
                id=f"finding-{marker}",
                project_id=project_id,
                rule_id="PLA-RTEST",
                severity="FAIL",
                internal_id=1,
                pole_number="P1",
                sheet="poles",
                field="test_field",
                message="Correct the test field",
                actual="bad",
                expected="good",
                related_poles_json="[]",
                status="OPEN",
            )
            db.add(finding)
            db.commit()
        finally:
            db.close()

        new_version = client.post(f"/api/projects/{project_id}/versions", headers=admin)
        assert new_version.status_code == 200
        assert new_version.json()["version_no"] == 2
        assert new_version.json()["status"] == "UPLOADING"
        assert new_version.json()["parent_version_id"] == v1["id"]

        correction = client.post(
            f"/api/findings/finding-{marker}/correction",
            headers=admin,
            json={"comment": "Update before resubmission"},
        )
        assert correction.status_code == 200, correction.text
        correction_id = correction.json()["id"]

        snap = client.get(f"/api/projects/{project_id}/workflow", headers=admin).json()
        assert snap["current_version"]["status"] == "CORRECTION_REQUIRED"
        assert any(x["id"] == correction_id and x["status"] == "OPEN" for x in snap["corrections"])

        resolved = client.post(f"/api/corrections/{correction_id}/resolve", headers=admin)
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "RESOLVED"

        approved = client.post(
            f"/api/projects/{project_id}/versions/{new_version.json()['id']}/approve",
            headers=admin,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"


def test_worker_claim_is_exclusive_and_failed_jobs_are_bounded_retryable():
    marker = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        project = Project(id=f"lease-{marker}", name="Lease Test", customer="PLA", status="PROCESSING")
        job = ProcessingJob(
            id=f"job-{marker}",
            project_id=project.id,
            job_type="INGEST",
            payload_json="{}",
            status="QUEUED",
            progress=0,
            stage="Queued",
        )
        db.add(project)
        db.add(job)
        db.commit()

        assert claim_next_job(db, "worker-a", lease_seconds=60, max_attempts=3) == job.id
        # The first claim moved the job to RUNNING, so it cannot be claimed twice.
        assert claim_next_job(db, "worker-b", lease_seconds=60, max_attempts=3) is None

        job = db.query(ProcessingJob).filter_by(id=job.id).first()
        job.status = "FAILED"
        db.commit()
        assert finish_job_lease(db, job.id, "worker-a", max_attempts=3) == "RETRY"
        assert db.query(ProcessingJob).filter_by(id=job.id).first().status == "QUEUED"
        lease = db.query(ProcessingLease).filter_by(job_id=job.id).first()
        assert lease.attempt_count == 1
    finally:
        db.close()
