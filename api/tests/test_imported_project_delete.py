"""Admin import listing and whole-project deletion regression tests."""
import json
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient

from app import storage
from app import main as main_module
from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import AuditLog, DatasetFile, Finding, LidarBlock, Notification, Pole, PoleAssignment, PolePresence, ProcessingJob, ProductionAnnotation, ProductionGeoFeature, Project, ReviewDecision, SceneFeature, User
from app.workflow import CorrectionRequest, DatasetVersion, FindingComparison, FindingRevision, ProcessingLease, QCRun, ReviewDecisionArchive, VersionFile


PASSWORD = "Imported-Project-Test-Pass-1!"


def account(role: str) -> str:
    email = f"import-delete-{role.lower()}-{uuid.uuid4().hex[:8]}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, name=f"{role} import test", role=role, password_hash=hash_password(PASSWORD), remote_access=True))
        db.commit()
    finally:
        db.close()
    return email


def auth(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def imported_project() -> dict[str, str]:
    marker = uuid.uuid4().hex[:8]
    project_id = f"import-delete-{marker}"
    version_id = uuid.uuid4().hex
    file_rows = [
        (uuid.uuid4().hex, "tile.laz", "LIDAR_SOURCE", f"{project_id}/source/tile.laz"),
        (uuid.uuid4().hex, "pole-lines.geojson", "GEOJSON", f"{project_id}/source/pole-lines.geojson"),
        (uuid.uuid4().hex, "poles.xlsx", "WORKBOOK", f"{project_id}/source/poles.xlsx"),
    ]
    copc_key = f"{project_id}/derived/tile.copc.laz"
    section_cache_key = f"{project_id}/analysis/section-cache.json"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name=f"Imported project {marker}", customer="PLA", crs="EPSG:6424", units="US survey foot", status="READY_FOR_QC"))
        db.add(AuditLog(actor="test", action="IMPORT_PROJECT", entity_type="project", entity_id=project_id, detail_json="{}"))
        db.add(DatasetVersion(id=version_id, project_id=project_id, version_no=1, status="READY_FOR_QC", created_by="test"))
        for file_id, filename, role, object_key in file_rows:
            db.add(DatasetFile(id=file_id, project_id=project_id, filename=filename, role=role, object_key=object_key,
                               content_type="application/octet-stream", size_bytes=12, status="UPLOADED"))
            db.add(VersionFile(version_id=version_id, file_id=file_id))
        db.add(LidarBlock(project_id=project_id, name="tile", source_object_key=file_rows[0][3], object_key=copc_key,
                          point_count=10, x_min=0, y_min=0, x_max=10, y_max=10, zmin=1, zmax=5, poles_json="[]"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-1", manifest_json="{}"))
        db.commit()
    finally:
        db.close()
    for _, _, _, object_key in file_rows:
        storage.upload_bytes(b"import-file", object_key)
    storage.upload_bytes(b"derived-copc", copc_key)
    storage.upload_bytes(b"cached-section", section_cache_key)
    return {"project_id": project_id, "version_id": version_id, "copc_key": copc_key,
            "section_cache_key": section_cache_key,
            **{f"{role.lower()}_key": object_key for _, _, role, object_key in file_rows}}


def seed_project_records(item: dict[str, str], admin_email: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(email=admin_email).one()
        geojson = db.query(DatasetFile).filter_by(project_id=item["project_id"], role="GEOJSON").one()
        job_id, run_id, finding_id = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
        result_key = f"{item['project_id']}/results/qc.json"
        db.add(ProcessingJob(id=job_id, project_id=item["project_id"], job_type="ANALYSIS", result_key=result_key, status="SUCCEEDED", stage="Done"))
        db.add(ProcessingLease(job_id=job_id, owner="test"))
        db.add(QCRun(id=run_id, project_id=item["project_id"], version_id=item["version_id"], processing_job_id=job_id,
                     status="SUCCEEDED", created_by=admin_email))
        db.add(Finding(id=finding_id, project_id=item["project_id"], rule_id="TEST", severity="FAIL", internal_id=1,
                       sheet="Poles", field="Height", message="Test finding"))
        db.add(ReviewDecision(finding_id=finding_id, reviewer_email=admin_email, decision="ACCEPTED"))
        db.add(FindingRevision(finding_id=finding_id, version_id=item["version_id"], qc_run_id=run_id))
        db.add(FindingComparison(project_id=item["project_id"], to_version_id=item["version_id"], status="NEW"))
        db.add(CorrectionRequest(id=uuid.uuid4().hex, project_id=item["project_id"], version_id=item["version_id"],
                                 finding_id=finding_id, created_by=admin_email))
        db.add(ReviewDecisionArchive(project_id=item["project_id"], version_id=item["version_id"], finding_id=finding_id,
                                     reviewer_email=admin_email, decision="ACCEPTED"))
        db.add(ProductionAnnotation(id=uuid.uuid4().hex, project_id=item["project_id"], block_name="tile", family="poles",
                                    feature_type="Pole_Base", x=1, y=2, z=3, created_by=admin_email, modified_by=admin_email))
        db.add(ProductionGeoFeature(project_id=item["project_id"], source_file_id=geojson.id, feature_index=0, geometry_type="Point",
                                   source_crs="EPSG:6424", source_geometry_json="{}", geometry_json="{}"))
        db.add(SceneFeature(project_id=item["project_id"], internal_id=1, feature_type="pole", payload_json="{}"))
        db.add(PoleAssignment(project_id=item["project_id"], pole_internal_id=1, user_id=admin.id, assigned_by=admin_email))
        db.add(PolePresence(project_id=item["project_id"], user_email=admin_email, pole_internal_id=1))
        db.add(Notification(user_id=admin.id, kind="TEST", title="Test", project_id=item["project_id"]))
        db.commit()
    finally:
        db.close()
    storage.upload_bytes(b"job-result", result_key)
    return {"job_id": job_id, "run_id": run_id, "finding_id": finding_id, "result_key": result_key}


def test_admin_import_list_groups_files_and_delete_removes_project_bundle(tmp_path, monkeypatch):
    initialize_schema()
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    admin_email, user_email = account("ADMIN"), account("USER")
    item = imported_project()
    related = seed_project_records(item, admin_email)

    with TestClient(app) as client:
        assert client.get("/api/admin/imports").status_code == 401
        user_headers = auth(client, user_email)
        admin_headers = auth(client, admin_email)
        assert client.get("/api/admin/imports", headers=user_headers).status_code == 403
        assert client.delete(f"/api/projects/{item['project_id']}").status_code == 401
        assert client.delete(f"/api/projects/{item['project_id']}", headers=user_headers).status_code == 403

        listed = client.get("/api/admin/imports", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        project = next(row for row in listed.json() if row["id"] == item["project_id"])
        assert {file["role"] for file in project["files"]} == {"LIDAR_SOURCE", "GEOJSON", "WORKBOOK"}
        assert client.delete(f"/api/projects/{item['project_id']}/uploads/not-a-file", headers=admin_headers).status_code == 405

        deleted = client.delete(f"/api/projects/{item['project_id']}", headers=admin_headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_objects"] == 6

    for object_key in (item["lidar_source_key"], item["geojson_key"], item["workbook_key"], item["copc_key"], item["section_cache_key"]):
        assert not storage.object_exists(object_key)
    db = SessionLocal()
    try:
        assert db.query(Project).filter_by(id=item["project_id"]).first() is None
        assert db.query(DatasetFile).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(LidarBlock).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(Pole).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ProductionAnnotation).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ProductionGeoFeature).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(SceneFeature).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(Finding).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ReviewDecision).filter_by(finding_id=related["finding_id"]).count() == 0
        assert db.query(FindingRevision).filter_by(qc_run_id=related["run_id"]).count() == 0
        assert db.query(FindingComparison).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(CorrectionRequest).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ReviewDecisionArchive).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(QCRun).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ProcessingLease).filter_by(job_id=related["job_id"]).count() == 0
        assert db.query(PoleAssignment).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(PolePresence).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(Notification).filter_by(project_id=item["project_id"]).count() == 0
        assert db.query(ProcessingJob).filter_by(project_id=item["project_id"]).count() == 0
        audit = db.query(AuditLog).filter_by(action="DELETE_PROJECT", entity_id=item["project_id"]).one()
        assert json.loads(audit.detail_json)["object_keys"]
        assert db.query(AuditLog).filter_by(action="IMPORT_PROJECT", entity_id=item["project_id"]).one()
        assert db.query(DatasetVersion).filter_by(id=item["version_id"]).first() is None
    finally:
        db.close()
    assert not storage.object_exists(related["result_key"])


def test_super_admin_can_list_and_delete_import(tmp_path, monkeypatch):
    initialize_schema()
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    super_email = account("SUPER_ADMIN")
    item = imported_project()
    with TestClient(app) as client:
        headers = auth(client, super_email)
        assert "project.delete" in client.get("/api/workspaces", headers=headers).json()["permissions"]
        assert any(row["id"] == item["project_id"] for row in client.get("/api/admin/imports", headers=headers).json())
        response = client.delete(f"/api/projects/{item['project_id']}", headers=headers)
        assert response.status_code == 200, response.text


def test_project_delete_refuses_active_approved_linked_and_shared_data(tmp_path, monkeypatch):
    initialize_schema()
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    admin_email = account("ADMIN")
    cases = [(imported_project(), "active"), (imported_project(), "approved"),
             (imported_project(), "linked"), (imported_project(), "shared_source"),
             (imported_project(), "shared_copc")]
    db = SessionLocal()
    try:
        for item, blocker in cases:
            project_id = item["project_id"]
            sibling_id = f"{blocker}-{uuid.uuid4().hex[:8]}"
            if blocker == "active":
                db.add(ProcessingJob(id=uuid.uuid4().hex, project_id=project_id, job_type="INGEST", status="RUNNING", stage="Processing"))
            elif blocker == "approved":
                db.query(DatasetVersion).filter_by(id=item["version_id"]).one().status = "APPROVED"
            elif blocker == "linked":
                db.add(Project(id=sibling_id, name="Linked QC", customer="PLA", crs="EPSG:6424", units="US survey foot", source_project_id=project_id))
            elif blocker == "shared_source":
                db.add(Project(id=sibling_id, name="Shared source", customer="PLA", crs="EPSG:6424", units="US survey foot"))
                db.add(DatasetFile(id=uuid.uuid4().hex, project_id=sibling_id, filename="shared.laz", role="LIDAR_SOURCE", object_key=item["lidar_source_key"]))
            elif blocker == "shared_copc":
                db.add(Project(id=sibling_id, name="Shared COPC", customer="PLA", crs="EPSG:6424", units="US survey foot"))
                db.add(LidarBlock(project_id=sibling_id, name=f"shared-{uuid.uuid4().hex[:6]}", source_object_key=None,
                                  object_key=item["copc_key"], point_count=1, x_min=0, y_min=0, x_max=1, y_max=1))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        headers = auth(client, admin_email)
        for item, blocker in cases:
            response = client.delete(f"/api/projects/{item['project_id']}", headers=headers)
            assert response.status_code == 409, (blocker, response.text)
            assert storage.object_exists(item["lidar_source_key"])
            assert storage.object_exists(item["copc_key"])
            db = SessionLocal()
            try:
                assert db.query(Project).filter_by(id=item["project_id"]).one()
            finally:
                db.close()


def test_project_delete_storage_failure_keeps_records_and_can_retry(tmp_path, monkeypatch):
    initialize_schema()
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    admin_email = account("ADMIN")
    item = imported_project()

    with TestClient(app) as client:
        headers = auth(client, admin_email)
        monkeypatch.setattr(main_module, "delete_objects", lambda _keys: (_ for _ in ()).throw(RuntimeError("storage unavailable")))
        failed = client.delete(f"/api/projects/{item['project_id']}", headers=headers)
        assert failed.status_code == 502
        assert "Retry" in failed.json()["detail"]
        db = SessionLocal()
        try:
            assert db.query(Project).filter_by(id=item["project_id"]).one()
            assert db.query(DatasetFile).filter_by(project_id=item["project_id"]).count() == 3
        finally:
            db.close()

        monkeypatch.setattr(main_module, "delete_objects", storage.delete_objects)
        retried = client.delete(f"/api/projects/{item['project_id']}", headers=headers)
        assert retried.status_code == 200, retried.text


def test_storage_list_objects_uses_paginated_s3_prefix(monkeypatch):
    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Bucket": "test-bucket", "Prefix": "project-id/"}
            return [{"Contents": [{"Key": "project-id/source/input.laz"}]}, {"Contents": [{"Key": "project-id/analysis/cache.json"}]}]

    class S3Client:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return Paginator()

    monkeypatch.setattr(storage, "MODE", "s3")
    monkeypatch.setattr(storage, "bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(storage, "_s3", S3Client)
    assert storage.list_objects("project-id/") == ["project-id/source/input.laz", "project-id/analysis/cache.json"]


def linked_qc_dataset(production: dict[str, str]) -> str:
    """A QC dataset as create_qc_dataset makes it: its file and block rows point at the Production objects."""
    qc_id = f"{production['project_id']}-qc"
    version_id = uuid.uuid4().hex
    db = SessionLocal()
    try:
        db.add(Project(id=qc_id, name="Imported project · QC", customer="PLA", crs="EPSG:6424", units="US survey foot",
                       status="READY_FOR_QC", source_project_id=production["project_id"]))
        db.add(DatasetVersion(id=version_id, project_id=qc_id, version_no=1, status="READY_FOR_QC", created_by="test"))
        file_id = uuid.uuid4().hex
        db.add(DatasetFile(id=file_id, project_id=qc_id, filename="tile.laz", role="LIDAR_SOURCE", object_key=production["lidar_source_key"],
                           content_type="application/octet-stream", size_bytes=12, status="UPLOADED"))
        db.add(VersionFile(version_id=version_id, file_id=file_id))
        db.add(LidarBlock(project_id=qc_id, name="tile", source_object_key=production["lidar_source_key"], object_key=production["copc_key"],
                          point_count=10, x_min=0, y_min=0, x_max=10, y_max=10, zmin=1, zmax=5, poles_json="[]"))
        db.commit()
    finally:
        db.close()
    storage.upload_bytes(b"qc-own-section", f"{qc_id}/versions/v1/analysis/section.json")
    return qc_id


def test_qc_dataset_is_deleted_without_touching_the_production_lidar_it_borrows(tmp_path, monkeypatch):
    initialize_schema()
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    admin_email = account("ADMIN")
    production = imported_project()
    qc_id = linked_qc_dataset(production)
    with TestClient(app) as client:
        headers = auth(client, admin_email)
        listed = {row["id"]: row for row in client.get("/api/admin/imports", headers=headers).json()}
        assert listed[production["project_id"]]["can_delete"] is False
        assert "Imported project · QC" in listed[production["project_id"]]["blocked_reason"]
        assert listed[qc_id]["can_delete"] is True and listed[qc_id]["source_project"]["id"] == production["project_id"]
        assert all(file["shared"] for file in listed[qc_id]["files"]), "borrowed Production files are flagged as shared"

        refused = client.delete(f"/api/projects/{production['project_id']}", headers=headers)
        assert refused.status_code == 409 and "Delete that QC dataset first" in refused.json()["detail"]

        deleted = client.delete(f"/api/projects/{qc_id}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_objects"] == 1, "only the QC dataset's own objects are deleted"
        assert not storage.object_exists(f"{qc_id}/versions/v1/analysis/section.json")
        for key in (production["lidar_source_key"], production["copc_key"], production["workbook_key"]):
            assert storage.object_exists(key), key
        db = SessionLocal()
        try:
            assert db.query(Project).filter_by(id=qc_id).first() is None
            assert db.query(LidarBlock).filter_by(project_id=production["project_id"]).count() == 1
            assert db.query(DatasetFile).filter_by(project_id=production["project_id"]).count() == 3
        finally:
            db.close()

        # With its QC dataset gone, the Production dataset can now be deleted.
        assert client.delete(f"/api/projects/{production['project_id']}", headers=headers).status_code == 200
        assert not storage.object_exists(production["lidar_source_key"])
