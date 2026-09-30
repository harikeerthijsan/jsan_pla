from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .models import AuditLog, DatasetFile, Finding, ProcessingJob, Project


def now_utc():
    return datetime.now(timezone.utc)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="UPLOADING", index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "version_no", name="uq_project_version_no"),)


class VersionFile(Base):
    __tablename__ = "version_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("dataset_files.id"), index=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("version_id", "file_id", name="uq_version_file"),)


class QCRun(Base):
    __tablename__ = "qc_runs"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    processing_job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FindingRevision(Base):
    __tablename__ = "finding_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    qc_run_id: Mapped[str] = mapped_column(ForeignKey("qc_runs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("finding_id", "version_id", name="uq_finding_version"),)


class FindingComparison(Base):
    __tablename__ = "finding_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    from_version_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    to_version_id: Mapped[str] = mapped_column(String(120), index=True)
    from_finding_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    to_finding_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingLease(Base):
    __tablename__ = "processing_leases"
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), primary_key=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


def _project_version_status(project: Project) -> str:
    return {
        "UPLOADING": "UPLOADING",
        "PROCESSING": "PROCESSING",
        "READY_FOR_REVIEW": "READY_FOR_QC",
        "READY_FOR_QC": "READY_FOR_QC",
        "CORRECTION_REQUIRED": "CORRECTION_REQUIRED",
        "APPROVED": "APPROVED",
        "FAILED": "CORRECTION_REQUIRED",
    }.get(project.status, "READY_FOR_QC")


def version_dict(v: DatasetVersion) -> dict:
    return {
        "id": v.id,
        "project_id": v.project_id,
        "version_no": v.version_no,
        "status": v.status,
        "parent_version_id": v.parent_version_id,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "submitted_at": v.submitted_at.isoformat() if v.submitted_at else None,
        "approved_at": v.approved_at.isoformat() if v.approved_at else None,
    }


def ensure_current_version(db: Session, project_id: str, actor: str = "system") -> DatasetVersion:
    v = (
        db.query(DatasetVersion)
        .filter_by(project_id=project_id)
        .order_by(DatasetVersion.version_no.desc())
        .first()
    )
    if v:
        return v
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    v = DatasetVersion(
        id=uuid.uuid4().hex,
        project_id=project_id,
        version_no=1,
        status=_project_version_status(project),
        created_by=actor,
        submitted_at=project.updated_at if project.status in {"READY_FOR_REVIEW", "READY_FOR_QC"} else None,
    )
    db.add(v)
    db.flush()
    for f in db.query(DatasetFile).filter_by(project_id=project_id).all():
        db.add(VersionFile(version_id=v.id, file_id=f.id))
    db.add(
        AuditLog(
            actor=actor,
            action="BASELINE_DATASET_VERSION",
            entity_type="dataset_version",
            entity_id=v.id,
            detail_json=json.dumps({"project_id": project_id, "version_no": 1}),
        )
    )
    db.flush()
    return v


def create_revision(db: Session, project_id: str, actor: str) -> DatasetVersion:
    parent = ensure_current_version(db, project_id, actor)
    if parent.status == "UPLOADING":
        return parent
    v = DatasetVersion(
        id=uuid.uuid4().hex,
        project_id=project_id,
        version_no=parent.version_no + 1,
        status="UPLOADING",
        parent_version_id=parent.id,
        created_by=actor,
    )
    db.add(v)
    db.flush()
    # Reuse immutable LiDAR sources unless Delivery uploads replacements for the revision.
    parent_files = (
        db.query(VersionFile, DatasetFile)
        .join(DatasetFile, DatasetFile.id == VersionFile.file_id)
        .filter(VersionFile.version_id == parent.id, DatasetFile.role == "LIDAR_SOURCE")
        .all()
    )
    for vf, f in parent_files:
        db.add(VersionFile(version_id=v.id, file_id=f.id, checksum_sha256=vf.checksum_sha256))
    project = db.query(Project).filter_by(id=project_id).first()
    if project:
        project.status = "UPLOADING"
    db.add(
        AuditLog(
            actor=actor,
            action="CREATE_DATASET_REVISION",
            entity_type="dataset_version",
            entity_id=v.id,
            detail_json=json.dumps({"project_id": project_id, "version_no": v.version_no, "parent_version_id": parent.id}),
        )
    )
    db.flush()
    return v


def attach_file_to_current_version(db: Session, project_id: str, file_id: str, actor: str) -> DatasetVersion:
    v = ensure_current_version(db, project_id, actor)
    if v.status in {"APPROVED", "ARCHIVED"}:
        raise HTTPException(409, "Create a new revision before uploading to an approved/archived version")
    exists = db.query(VersionFile).filter_by(version_id=v.id, file_id=file_id).first()
    if not exists:
        db.add(VersionFile(version_id=v.id, file_id=file_id))
    db.flush()
    return v


def version_files(db: Session, version_id: str) -> list[DatasetFile]:
    ids = [x.file_id for x in db.query(VersionFile).filter_by(version_id=version_id).all()]
    return db.query(DatasetFile).filter(DatasetFile.id.in_(ids)).order_by(DatasetFile.created_at).all() if ids else []


def set_file_checksum(db: Session, version_id: str, file_id: str, checksum: str) -> None:
    vf = db.query(VersionFile).filter_by(version_id=version_id, file_id=file_id).first()
    if vf:
        vf.checksum_sha256 = checksum
        db.flush()


def get_file_checksum(db: Session, version_id: str, file_id: str) -> str | None:
    vf = db.query(VersionFile).filter_by(version_id=version_id, file_id=file_id).first()
    return vf.checksum_sha256 if vf else None


def create_qc_run(db: Session, project_id: str, job_id: str, actor: str) -> tuple[DatasetVersion, QCRun]:
    v = ensure_current_version(db, project_id, actor)
    v.status = "PROCESSING"
    v.submitted_at = now_utc()
    run = QCRun(
        id=uuid.uuid4().hex,
        project_id=project_id,
        version_id=v.id,
        processing_job_id=job_id,
        status="QUEUED",
        created_by=actor,
    )
    db.add(run)
    db.flush()
    return v, run


def _finding_signature(f: Finding) -> tuple:
    return (
        f.rule_id,
        int(f.internal_id),
        f.field or "",
        f.pole_number or "",
        f.actual or "",
        f.expected or "",
    )


def record_findings_for_run(db: Session, project_id: str, version_id: str, qc_run_id: str) -> dict:
    current = db.query(Finding).filter_by(project_id=project_id).all()
    for f in current:
        if not db.query(FindingRevision).filter_by(finding_id=f.id, version_id=version_id).first():
            db.add(FindingRevision(finding_id=f.id, version_id=version_id, qc_run_id=qc_run_id))

    version = db.query(DatasetVersion).filter_by(id=version_id).first()
    db.query(FindingComparison).filter_by(to_version_id=version_id).delete()
    stats = {"NEW": 0, "STILL_OPEN": 0, "RESOLVED": 0}
    if version and version.parent_version_id:
        parent_links = db.query(FindingRevision).filter_by(version_id=version.parent_version_id).all()
        parent_findings = {
            x.finding_id: db.query(Finding).filter_by(id=x.finding_id).first() for x in parent_links
        }
        old_by_sig = {_finding_signature(f): f for f in parent_findings.values() if f}
        new_by_sig = {_finding_signature(f): f for f in current}
        for sig in sorted(set(old_by_sig) | set(new_by_sig), key=str):
            old = old_by_sig.get(sig)
            new = new_by_sig.get(sig)
            status = "STILL_OPEN" if old and new else ("RESOLVED" if old else "NEW")
            stats[status] += 1
            db.add(
                FindingComparison(
                    project_id=project_id,
                    from_version_id=version.parent_version_id,
                    to_version_id=version_id,
                    from_finding_id=old.id if old else None,
                    to_finding_id=new.id if new else None,
                    status=status,
                )
            )
            if status == "RESOLVED" and old:
                for correction in db.query(CorrectionRequest).filter_by(finding_id=old.id, status="OPEN").all():
                    correction.status = "RESOLVED"
                    correction.resolved_by = "worker"
                    correction.resolved_at = now_utc()

    db.flush()
    return stats


def complete_qc_run(db: Session, qc_run_id: str | None, success: bool, summary: dict | None = None) -> None:
    if not qc_run_id:
        return
    run = db.query(QCRun).filter_by(id=qc_run_id).first()
    if not run:
        return
    run.status = "SUCCEEDED" if success else "FAILED"
    run.finished_at = now_utc()
    run.summary_json = json.dumps(summary or {})
    v = db.query(DatasetVersion).filter_by(id=run.version_id).first()
    if v:
        v.status = "READY_FOR_QC" if success else "CORRECTION_REQUIRED"
    db.flush()


def create_correction(db: Session, finding: Finding, actor: str, comment: str | None) -> CorrectionRequest:
    link = (
        db.query(FindingRevision)
        .filter_by(finding_id=finding.id)
        .order_by(FindingRevision.id.desc())
        .first()
    )
    version = db.query(DatasetVersion).filter_by(id=link.version_id).first() if link else ensure_current_version(db, finding.project_id, actor)
    existing = db.query(CorrectionRequest).filter_by(finding_id=finding.id, status="OPEN").first()
    if existing:
        if comment:
            existing.comment = comment
        return existing
    row = CorrectionRequest(
        id=uuid.uuid4().hex,
        project_id=finding.project_id,
        version_id=version.id,
        finding_id=finding.id,
        comment=comment,
        created_by=actor,
    )
    db.add(row)
    version.status = "CORRECTION_REQUIRED"
    project = db.query(Project).filter_by(id=finding.project_id).first()
    if project:
        project.status = "CORRECTION_REQUIRED"
    db.add(
        AuditLog(
            actor=actor,
            action="REQUEST_CORRECTION",
            entity_type="finding",
            entity_id=finding.id,
            detail_json=json.dumps({"correction_id": row.id, "comment": comment}),
        )
    )
    db.flush()
    return row


def resolve_correction(db: Session, correction_id: str, actor: str) -> CorrectionRequest:
    row = db.query(CorrectionRequest).filter_by(id=correction_id).first()
    if not row:
        raise HTTPException(404, "Correction request not found")
    row.status = "RESOLVED"
    row.resolved_by = actor
    row.resolved_at = now_utc()
    db.add(AuditLog(actor=actor, action="RESOLVE_CORRECTION", entity_type="correction", entity_id=row.id, detail_json="{}"))
    db.flush()
    return row


def approve_version(db: Session, project_id: str, version_id: str, actor: str) -> DatasetVersion:
    v = db.query(DatasetVersion).filter_by(id=version_id, project_id=project_id).first()
    if not v:
        raise HTTPException(404, "Dataset version not found")
    open_corrections = db.query(CorrectionRequest).filter_by(project_id=project_id, status="OPEN").count()
    if open_corrections:
        raise HTTPException(409, f"{open_corrections} correction request(s) remain open")
    v.status = "APPROVED"
    v.approved_at = now_utc()
    project = db.query(Project).filter_by(id=project_id).first()
    if project:
        project.status = "APPROVED"
    db.add(AuditLog(actor=actor, action="APPROVE_DATASET_VERSION", entity_type="dataset_version", entity_id=v.id, detail_json="{}"))
    db.flush()
    return v


def workflow_snapshot(db: Session, project_id: str, actor: str) -> dict:
    current = ensure_current_version(db, project_id, actor)
    versions = db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).all()
    corrections = db.query(CorrectionRequest).filter_by(project_id=project_id).order_by(CorrectionRequest.created_at.desc()).all()
    comparisons = db.query(FindingComparison).filter_by(to_version_id=current.id).all()
    runs = db.query(QCRun).filter_by(project_id=project_id).order_by(QCRun.created_at.desc()).limit(20).all()
    return {
        "current_version": version_dict(current),
        "versions": [version_dict(v) for v in versions],
        "corrections": [
            {
                "id": c.id,
                "version_id": c.version_id,
                "finding_id": c.finding_id,
                "status": c.status,
                "comment": c.comment,
                "created_by": c.created_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_by": c.resolved_by,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            }
            for c in corrections
        ],
        "comparison": {
            "NEW": sum(x.status == "NEW" for x in comparisons),
            "STILL_OPEN": sum(x.status == "STILL_OPEN" for x in comparisons),
            "RESOLVED": sum(x.status == "RESOLVED" for x in comparisons),
        },
        "qc_runs": [
            {
                "id": r.id,
                "version_id": r.version_id,
                "status": r.status,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ],
    }


def _recover_stale_leases(db: Session, max_attempts: int) -> None:
    now = now_utc()
    stale = db.query(ProcessingLease).filter(ProcessingLease.lease_expires_at.is_not(None), ProcessingLease.lease_expires_at < now).all()
    for lease in stale:
        job = db.query(ProcessingJob).filter_by(id=lease.job_id).first()
        if job and job.status == "RUNNING":
            if lease.attempt_count < max_attempts:
                job.status = "QUEUED"
                job.stage = f"Recovered stale worker lease; retry {lease.attempt_count + 1}/{max_attempts}"
            else:
                job.status = "FAILED"
                job.stage = "Failed after worker lease expiry"
        lease.owner = None
        lease.lease_expires_at = None
    db.flush()


def claim_next_job(db: Session, worker_id: str, lease_seconds: int = 180, max_attempts: int = 3) -> str | None:
    _recover_stale_leases(db, max_attempts)
    q = db.query(ProcessingJob).filter(ProcessingJob.status == "QUEUED").order_by(ProcessingJob.created_at)
    if db.bind and db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = q.first()
    if not job:
        db.commit()
        return None
    lease = db.query(ProcessingLease).filter_by(job_id=job.id).first()
    if not lease:
        lease = ProcessingLease(job_id=job.id, attempt_count=0)
        db.add(lease)
        db.flush()
    lease.attempt_count += 1
    lease.owner = worker_id
    lease.heartbeat_at = now_utc()
    lease.lease_expires_at = lease.heartbeat_at + timedelta(seconds=lease_seconds)
    job.status = "RUNNING"
    job.started_at = job.started_at or now_utc()
    job.stage = "Worker claimed job"
    db.commit()
    return job.id


def heartbeat_job(db: Session, job_id: str, worker_id: str, lease_seconds: int = 180) -> None:
    lease = db.query(ProcessingLease).filter_by(job_id=job_id, owner=worker_id).first()
    if not lease:
        return
    lease.heartbeat_at = now_utc()
    lease.lease_expires_at = lease.heartbeat_at + timedelta(seconds=lease_seconds)
    db.commit()


def finish_job_lease(db: Session, job_id: str, worker_id: str, max_attempts: int = 3) -> str:
    job = db.query(ProcessingJob).filter_by(id=job_id).first()
    lease = db.query(ProcessingLease).filter_by(job_id=job_id).first()
    if not job:
        return "MISSING"
    attempts = lease.attempt_count if lease else 1
    if lease and lease.owner == worker_id:
        lease.owner = None
        lease.lease_expires_at = None
    if job.status == "FAILED" and attempts < max_attempts:
        job.status = "QUEUED"
        job.stage = f"Retry queued ({attempts + 1}/{max_attempts})"
        project = db.query(Project).filter_by(id=job.project_id).first()
        if project:
            project.status = "PROCESSING"
        outcome = "RETRY"
    else:
        outcome = job.status
    db.commit()
    return outcome
