"""Workbook format of a dataset: PLA-1 (single ZoneName sheet, filled by hand) or PLA-2 (COLLECTION, filled from points).

New imports choose the format. Datasets imported before that are detected from their current workbook, once:
lazily when the API needs it, and for all of them when a worker starts (so a deployed server fills every existing
dataset after the release). Datasets imported without any workbook stay unset until an admin chooses.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .collection_workbook import detect_workbook_format
from .models import Project
from .storage import read_bytes
from .workflow import DatasetVersion, version_files


def latest_workbook_file(db: Session, project_id: str):
    """(current, source): the workbook the dataset works from now (latest saved edit, else the upload), and the upload."""
    version = db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    if not version:
        return None, None
    files = [f for f in version_files(db, version.id) if f.status == "UPLOADED"]
    edited = [f for f in files if f.role == "WORKBOOK_EDITED"]
    sources = [f for f in files if f.role == "WORKBOOK"]
    current = (edited or sources)[-1] if (edited or sources) else None
    return current, (sources[-1] if sources else None)


def detect_project_format(db: Session, project: Project) -> str | None:
    current, _ = latest_workbook_file(db, project.id)
    if not current:
        return None
    try:
        return detect_workbook_format(read_bytes(current.object_key))
    except FileNotFoundError:
        return None


def resolve_workbook_format(db: Session, project: Project) -> str | None:
    """The stored format, or the detected one (then stored)."""
    if project.workbook_format:
        return project.workbook_format
    detected = detect_project_format(db, project)
    if detected:
        project.workbook_format = detected
        db.commit()
    return detected


def backfill_workbook_formats(db: Session, log=print) -> dict:
    """Detect and store the format of every dataset that has none yet. Safe to run repeatedly and from several workers."""
    counts = {"detected": 0, "no_workbook": 0, "failed": 0}
    ids = [pid for (pid,) in db.query(Project.id).filter(Project.workbook_format.is_(None)).all()]
    for project_id in ids:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project or project.workbook_format:
            continue
        try:
            if resolve_workbook_format(db, project):
                counts["detected"] += 1
            else:
                counts["no_workbook"] += 1
        except Exception as exc:  # one unreadable workbook must not stop the rest
            db.rollback()
            counts["failed"] += 1
            log(f"Workbook format backfill: {project_id} skipped ({exc.__class__.__name__})")
    return counts
