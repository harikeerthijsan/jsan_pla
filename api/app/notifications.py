"""In-app notifications: who hears about QC results, corrections, approvals and pole assignments.

Rules: a person is never notified about their own action; inactive accounts are skipped; users never see an
admin's name (they read "an admin"). Callers wrap these helpers so a notification problem never fails the action
that triggered it (see ``safely``).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Finding, Notification, iso_utc, Pole, PoleAssignment, ProductionAnnotation, Project, User
from .pipeline import dataset_pair
from .rbac import has_permission
from .workbook_editor import normalize_pole_number

log = logging.getLogger(__name__)
router = APIRouter()
MAX_POLES_LISTED = 5


def safely(action, *args, **kwargs) -> None:
    """Run a notify_* helper after the triggering action has committed, in its own commit.

    A failure rolls back only the notifications and is logged, so the action itself always stands.
    """
    db = args[0]
    try:
        action(*args, **kwargs)
        db.commit()
    except Exception:  # noqa: BLE001 - notifications are best effort by design
        db.rollback()
        log.exception("Notification %s failed", getattr(action, "__name__", action))


def _admins(db: Session) -> list[User]:
    return [u for u in db.query(User).filter(func.upper(User.role) == "ADMIN").all() if u.is_active]


def _who(actor_email: str | None, recipient: User, users: dict[str, User]) -> str:
    actor = users.get(actor_email or "")
    if not actor:
        return actor_email or "someone"
    if (actor.role or "").upper() == "ADMIN" and not has_permission(recipient, "work.view_all"):
        return "an admin"
    return actor.username or actor.name or actor.email


def _send(db: Session, recipients, *, kind: str, title: str, body: str | None = None, project_id: str | None = None,
          pole_internal_id: int | None = None, link: dict | None = None, actor_email: str | None = None) -> int:
    sent, seen = 0, set()
    for user in recipients:
        if not user or not user.is_active or user.id in seen or user.email == actor_email:
            continue
        seen.add(user.id)
        text = body(user) if callable(body) else body
        db.add(Notification(user_id=user.id, kind=kind, title=title[:300], body=text, project_id=project_id,
                            pole_internal_id=pole_internal_id, link_json=json.dumps(link or {})))
        sent += 1
    db.flush()
    return sent


def pole_owners(db: Session, production_id: str, pole_ids) -> dict[int, User]:
    """The person responsible for each pole: its assignee, else whoever last saved a point on it."""
    pole_ids = list(set(pole_ids))
    if not pole_ids:
        return {}
    users_by_id = {u.id: u for u in db.query(User).all()}
    users_by_email = {u.email: u for u in users_by_id.values()}
    owners = {a.pole_internal_id: users_by_id.get(a.user_id) for a in db.query(PoleAssignment).filter(
        PoleAssignment.project_id == production_id, PoleAssignment.pole_internal_id.in_(pole_ids)).all()}
    latest: dict[int, ProductionAnnotation] = {}
    for row in db.query(ProductionAnnotation).filter(ProductionAnnotation.project_id == production_id,
                                                     ProductionAnnotation.pole_internal_id.in_(pole_ids)).all():
        if row.pole_internal_id not in latest or (row.updated_at or row.created_at) > (latest[row.pole_internal_id].updated_at or latest[row.pole_internal_id].created_at):
            latest[row.pole_internal_id] = row
    for pole_id, row in latest.items():
        if not owners.get(pole_id):
            owners[pole_id] = users_by_email.get(row.modified_by)
    return {pole_id: user for pole_id, user in owners.items() if user}


def _production_pole_ids(db: Session, production: Project) -> dict[str, int]:
    out: dict[str, int] = {}
    for pole in db.query(Pole).filter_by(project_id=production.id).all():
        key = normalize_pole_number(pole.pole_number)
        if key:
            out.setdefault(key, pole.internal_id)
    return out


def _pole_list(numbers: list[str]) -> str:
    shown = ", ".join(numbers[:MAX_POLES_LISTED])
    return shown + (f" and {len(numbers) - MAX_POLES_LISTED} more" if len(numbers) > MAX_POLES_LISTED else "")


def notify_qc_finished(db: Session, qc_project: Project, started_by: str | None, success: bool, error: str | None = None) -> None:
    production, qc = dataset_pair(db, qc_project)
    users = {u.email: u for u in db.query(User).all()}
    summary_recipients = _admins(db) + ([users[started_by]] if started_by in users else [])
    qc_link = {"workspace": "QC", "project_id": qc.id}
    if not success:
        _send(db, summary_recipients, kind="QC_FAILED", title=f"QC failed on {qc.name}",
              body=(error or "The QC run did not complete.")[:500], project_id=qc.id, link=qc_link)
        return
    findings = db.query(Finding).filter(Finding.project_id == qc.id, Finding.severity.in_(["FAIL", "REVIEW"])).all()
    fail = sum(f.severity == "FAIL" for f in findings)
    review = len(findings) - fail
    _send(db, summary_recipients, kind="QC_FINISHED", title=f"QC finished on {qc.name}: {fail} FAIL, {review} REVIEW",
          body="Open the QC tab to review the findings.", project_id=qc.id, link=qc_link)
    if not production or not findings:
        return
    production_ids = _production_pole_ids(db, production)
    by_pole: dict[int, list[Finding]] = defaultdict(list)
    for finding in findings:
        pole_id = production_ids.get(normalize_pole_number(finding.pole_number))
        if pole_id is not None:
            by_pole[pole_id].append(finding)
    per_owner: dict[int, dict] = {}
    for pole_id, user in pole_owners(db, production.id, by_pole).items():
        entry = per_owner.setdefault(user.id, {"user": user, "fail": 0, "review": 0, "poles": [], "first": pole_id})
        entry["fail"] += sum(f.severity == "FAIL" for f in by_pole[pole_id])
        entry["review"] += sum(f.severity == "REVIEW" for f in by_pole[pole_id])
        entry["poles"].append(by_pole[pole_id][0].pole_number or str(pole_id))
        entry["first"] = min(entry["first"], pole_id)
    for entry in per_owner.values():
        issues = entry["fail"] + entry["review"]
        _send(db, [entry["user"]], kind="QC_ISSUES_ON_YOUR_POLES",
              title=f"QC found {issues} issue{'' if issues == 1 else 's'} on your poles",
              body=f"{entry['fail']} FAIL · {entry['review']} REVIEW on {_pole_list(sorted(entry['poles']))} in {production.name}.",
              project_id=production.id, pole_internal_id=entry["first"],
              link={"workspace": "PRODUCTION", "project_id": production.id, "pole_internal_id": entry["first"]})


def notify_correction_requested(db: Session, finding: Finding, comment: str | None, actor_email: str) -> None:
    project = db.query(Project).filter_by(id=finding.project_id).first()
    if not project:
        return
    production, qc = dataset_pair(db, project)
    note = f" Note: {comment}" if comment else ""
    body = f"{finding.rule_id} {finding.severity}: {(finding.message or '').rstrip('. ')}.{note}"[:500]
    pole_label = finding.pole_number or f"ID {finding.internal_id}"
    if production:
        pole_id = _production_pole_ids(db, production).get(normalize_pole_number(finding.pole_number))
        owner = pole_owners(db, production.id, [pole_id]).get(pole_id) if pole_id is not None else None
        if owner:
            _send(db, [owner], kind="CORRECTION_REQUESTED", title=f"Correction requested on pole {pole_label}", body=body,
                  project_id=production.id, pole_internal_id=pole_id, actor_email=actor_email,
                  link={"workspace": "PRODUCTION", "project_id": production.id, "pole_internal_id": pole_id})
            return
    # Nobody owns the pole yet: admins decide who fixes it.
    _send(db, _admins(db), kind="CORRECTION_REQUESTED", title=f"Correction requested on pole {pole_label} (no owner yet)", body=body,
          project_id=qc.id, pole_internal_id=finding.internal_id, actor_email=actor_email,
          link={"workspace": "DELIVERY", "project_id": qc.id})


def notify_correction_resolved(db: Session, correction, pole_number: str | None, internal_id: int | None, actor_email: str) -> None:
    from .workflow import CorrectionRequest  # local import: workflow imports models at module load

    project = db.query(Project).filter_by(id=correction.project_id).first()
    if not project:
        return
    users = {u.email: u for u in db.query(User).all()}
    remaining = db.query(CorrectionRequest).filter_by(project_id=project.id, status="OPEN").count()
    pole_label = pole_number or (f"ID {internal_id}" if internal_id is not None else "a pole")
    title = (f"All corrections fixed on {project.name} — ready for re-check" if remaining == 0
             else f"Pole {pole_label} fixed — ready for re-check")
    recipients = ([users[correction.created_by]] if correction.created_by in users else []) + _admins(db)
    _send(db, recipients, kind="CORRECTION_RESOLVED", title=title,
          body=lambda recipient: f"Pole {pole_label} fixed by {_who(actor_email, recipient, users)}. "
                                 + (f"{remaining} correction{'' if remaining == 1 else 's'} still open." if remaining else "Run QC again to confirm."),
          project_id=project.id, pole_internal_id=internal_id, actor_email=actor_email,
          link={"workspace": "QC", "project_id": project.id, "pole_internal_id": internal_id})


def notify_version_approved(db: Session, project: Project, version_no: int, actor_email: str) -> None:
    _send(db, _admins(db), kind="VERSION_APPROVED", title=f"{project.name} v{version_no} approved — deliverable package ready",
          body="Download the package from the Delivery tab.", project_id=project.id, actor_email=actor_email,
          link={"workspace": "DELIVERY", "project_id": project.id})


def notify_poles_assigned(db: Session, project: Project, user: User, pole_ids: list[int], actor_email: str) -> None:
    count = len(pole_ids)
    _send(db, [user], kind="POLES_ASSIGNED", title=f"You were assigned {count} pole{'' if count == 1 else 's'}",
          body=f"In {project.name}. Use the Mine filter in the pole list to see them.", project_id=project.id,
          pole_internal_id=min(pole_ids) if pole_ids else None, actor_email=actor_email,
          link={"workspace": "PRODUCTION", "project_id": project.id, "pole_internal_id": min(pole_ids) if pole_ids else None})


def notification_dict(row: Notification) -> dict:
    return {"id": row.id, "kind": row.kind, "title": row.title, "body": row.body, "project_id": row.project_id,
            "pole_internal_id": row.pole_internal_id, "link": json.loads(row.link_json or "{}"),
            "created_at": iso_utc(row.created_at), "read": row.read_at is not None}


@router.get("/api/notifications")
def list_notifications(limit: int = Query(30, ge=1, le=100), u: User = Depends(current_user), db: Session = Depends(get_db)):
    unread = db.query(func.count(Notification.id)).filter(Notification.user_id == u.id, Notification.read_at.is_(None)).scalar() or 0
    rows = (db.query(Notification).filter(Notification.user_id == u.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all())
    return {"unread": unread, "items": [notification_dict(row) for row in rows]}


@router.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.query(Notification).filter_by(id=notification_id, user_id=u.id).first()
    if not row:
        raise HTTPException(404, "Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return notification_dict(row)


@router.post("/api/notifications/read-all")
def read_all_notifications(u: User = Depends(current_user), db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.user_id == u.id, Notification.read_at.is_(None)).update(
        {Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {"ok": True, "marked": count}
