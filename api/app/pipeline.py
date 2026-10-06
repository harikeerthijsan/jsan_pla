"""Production → QC → Delivery pipeline for one dataset pair.

A Production dataset is QC-checked in a linked QC dataset (``Project.source_project_id``). Whichever of the two is
selected, the pipeline resolves the pair so Production, QC and Delivery show the same picture. Corrections raised in
QC are listed with the Production pole that has to be fixed.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import Finding, Pole, ProcessingJob, ProductionAnnotation, Project
from .workbook_editor import normalize_pole_number
from .workflow import CorrectionRequest, DatasetVersion, FindingRevision, QCRun, version_files

POLE_BASE = {"Pole_Base", "Pole Base / Ground Point"}
POLE_TOP = {"Pole_Top", "Pole Top Point"}


def production_project_ids(db: Session) -> set[str]:
    return {row[0] for row in db.query(ProcessingJob.project_id).filter_by(job_type="LIDAR_INGEST").distinct().all()}


def dataset_pair(db: Session, project: Project) -> tuple[Project | None, Project | None]:
    """(production, qc) for any dataset; classic QC-only datasets return (None, project)."""
    if project.source_project_id:
        return db.query(Project).filter_by(id=project.source_project_id).first(), project
    if project.id in production_project_ids(db):
        qc = db.query(Project).filter_by(source_project_id=project.id).order_by(Project.created_at.desc()).first()
        return project, qc
    return None, project


def _current_version(db: Session, project_id: str) -> DatasetVersion | None:
    return db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()


def production_summary(db: Session, project: Project) -> dict:
    poles = db.query(Pole).filter_by(project_id=project.id).all()
    rows = db.query(ProductionAnnotation.pole_internal_id, ProductionAnnotation.feature_type).filter_by(project_id=project.id).all()
    base = {pole_id for pole_id, feature in rows if feature in POLE_BASE}
    top = {pole_id for pole_id, feature in rows if feature in POLE_TOP}
    touched = {pole_id for pole_id, _ in rows}
    version = _current_version(db, project.id)
    files = [f for f in version_files(db, version.id) if f.status == "UPLOADED"] if version else []
    excel = next((f for f in reversed(files) if f.role == "WORKBOOK"), None)
    return {
        "id": project.id, "name": project.name, "status": project.status,
        "poles": len(poles),
        "poles_done": sum(1 for p in poles if p.internal_id in base and p.internal_id in top),
        "poles_in_progress": sum(1 for p in poles if p.internal_id in touched and not (p.internal_id in base and p.internal_id in top)),
        "points": len(rows),
        "excel": excel.filename if excel else None,
        "excel_edited": any(f.role == "WORKBOOK_EDITED" for f in files),
        "has_geojson": any(f.role == "GEOJSON" for f in files),
    }


def qc_summary(db: Session, project: Project) -> dict:
    version = _current_version(db, project.id)
    runs = db.query(QCRun).filter_by(project_id=project.id).order_by(QCRun.created_at.desc()).all()
    latest = runs[0] if runs else None
    findings = db.query(Finding.severity, Finding.status).filter_by(project_id=project.id).all()
    files = [f for f in version_files(db, version.id) if f.status == "UPLOADED"] if version else []
    return {
        "id": project.id, "name": project.name, "status": project.status,
        "version_no": version.version_no if version else None, "version_status": version.status if version else None,
        "has_excel": any(f.role == "WORKBOOK" for f in files),
        "runs": len(runs),
        "latest_run": {"status": latest.status, "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
                       "job_id": latest.processing_job_id} if latest else None,
        "findings": {
            "fail": sum(1 for severity, _ in findings if severity == "FAIL"),
            "review": sum(1 for severity, _ in findings if severity == "REVIEW"),
            "unverifiable": sum(1 for severity, _ in findings if severity == "UNVERIFIABLE"),
            "open": sum(1 for _, status in findings if status == "OPEN"),
        },
    }


def corrections(db: Session, qc: Project, production: Project | None) -> list[dict]:
    rows = db.query(CorrectionRequest).filter_by(project_id=qc.id).order_by(CorrectionRequest.created_at.desc()).all()
    findings = {f.id: f for f in db.query(Finding).filter(Finding.id.in_([r.finding_id for r in rows])).all()} if rows else {}
    production_poles = {}
    if production:
        for pole in db.query(Pole).filter_by(project_id=production.id).all():
            production_poles.setdefault(normalize_pole_number(pole.pole_number), pole.internal_id)
    out = []
    for row in rows:
        finding = findings.get(row.finding_id)
        if finding is None:
            # The finding was rebuilt by a later QC run; its last snapshot still describes it.
            revision = db.query(FindingRevision).filter_by(finding_id=row.finding_id).order_by(FindingRevision.id.desc()).first()
            snapshot = json.loads(revision.snapshot_json or "{}") if revision else {}
        else:
            snapshot = {"rule_id": finding.rule_id, "severity": finding.severity, "pole_number": finding.pole_number,
                        "internal_id": finding.internal_id, "message": finding.message, "field": finding.field}
        number = snapshot.get("pole_number")
        out.append({
            "id": row.id, "status": row.status, "comment": row.comment, "finding_id": row.finding_id,
            "rule_id": snapshot.get("rule_id"), "severity": snapshot.get("severity"), "message": snapshot.get("message"),
            "field": snapshot.get("field"), "pole_number": number,
            "production_pole_internal_id": production_poles.get(normalize_pole_number(number)) if number else None,
            "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None,
            "resolved_by": row.resolved_by, "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        })
    return out


def pipeline(db: Session, project: Project) -> dict:
    production, qc = dataset_pair(db, project)
    qc_info = qc_summary(db, qc) if qc else None
    delivery_target = qc or production
    version = _current_version(db, delivery_target.id) if delivery_target else None
    correction_rows = corrections(db, qc, production) if qc else []
    return {
        "selected_id": project.id,
        "production": production_summary(db, production) if production else None,
        "qc": qc_info,
        "delivery": {
            "project_id": delivery_target.id if delivery_target else None,
            "version_id": version.id if version else None,
            "version_no": version.version_no if version else None,
            "version_status": version.status if version else None,
            "approved": bool(version and version.status == "APPROVED"),
            "open_corrections": sum(1 for row in correction_rows if row["status"] == "OPEN"),
        },
        "corrections": correction_rows,
    }
