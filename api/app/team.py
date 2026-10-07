"""Team workflow for Production datasets: pole assignments, live "open by" presence and the admin progress dashboard.

Assignments are guidance, not locks: users may still edit each other's work. Admins stay invisible to users,
matching the Production work-visibility rule. All state is in the database, so every API process agrees.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .notifications import notify_poles_assigned, safely
from .models import iso_utc, AuditLog, Finding, Pole, PoleAssignment, PolePresence, ProductionAnnotation, Project, User
from .pipeline import POLE_BASE, POLE_TOP, dataset_pair
from .rbac import has_permission, require_permission
from .workbook_editor import normalize_pole_number

router = APIRouter()

PRESENCE_ACTIVE_SECONDS = 75
PRESENCE_RETENTION = timedelta(days=1)


def hidden_authors(db: Session, u: User) -> set[str]:
    # Users see every user's Production work but never an admin's; admins see everything.
    if has_permission(u, "work.view_all"):
        return set()
    return {email for (email,) in db.query(User.email).filter(func.upper(User.role) == "ADMIN").all()}


def display_name(user: User | None, fallback: str) -> str:
    return (user.username or user.name or user.email) if user else fallback


class AssignmentIn(BaseModel):
    user_id: int | None = None
    pole_internal_ids: list[int] = Field(min_length=1, max_length=5000)


class PresenceIn(BaseModel):
    pole_internal_id: int | None = None


def _project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _assignment_rows(db: Session, project_id: str) -> list[dict]:
    rows = (db.query(PoleAssignment, User).join(User, User.id == PoleAssignment.user_id)
            .filter(PoleAssignment.project_id == project_id).order_by(PoleAssignment.pole_internal_id).all())
    return [{"pole_internal_id": a.pole_internal_id, "user_id": user.id, "username": display_name(user, user.email),
             "name": user.name, "assigned_at": iso_utc(a.assigned_at)} for a, user in rows]


@router.get("/api/projects/{project_id}/pole-assignments")
def list_pole_assignments(project_id: str, u: User = Depends(require_permission("project.read")), db: Session = Depends(get_db)):
    _project(db, project_id)
    return _assignment_rows(db, project_id)


@router.put("/api/projects/{project_id}/pole-assignments")
def assign_poles(project_id: str, body: AssignmentIn, u: User = Depends(require_permission("user.manage")), db: Session = Depends(get_db)):
    _project(db, project_id)
    pole_ids = sorted(set(body.pole_internal_ids))
    known = {pid for (pid,) in db.query(Pole.internal_id).filter(Pole.project_id == project_id, Pole.internal_id.in_(pole_ids)).all()}
    unknown = [pid for pid in pole_ids if pid not in known]
    if unknown:
        raise HTTPException(422, f"These internal_id values are not poles in this dataset: {', '.join(map(str, unknown[:20]))}")
    assignee = None
    if body.user_id is not None:
        assignee = db.query(User).filter_by(id=body.user_id).first()
        if not assignee or not assignee.is_active:
            raise HTTPException(422, "Choose an active user to assign these poles to")
    db.query(PoleAssignment).filter(PoleAssignment.project_id == project_id, PoleAssignment.pole_internal_id.in_(pole_ids)).delete(synchronize_session=False)
    if assignee:
        now = datetime.now(timezone.utc)
        db.add_all([PoleAssignment(project_id=project_id, pole_internal_id=pid, user_id=assignee.id, assigned_by=u.email, assigned_at=now) for pid in pole_ids])
    db.add(AuditLog(actor=u.email, action="ASSIGN_POLES" if assignee else "UNASSIGN_POLES", entity_type="project", entity_id=project_id,
                    detail_json=json.dumps({"user": assignee.email if assignee else None, "poles": len(pole_ids), "pole_internal_ids": pole_ids[:200]})))
    db.commit()
    if assignee:
        safely(notify_poles_assigned, db, _project(db, project_id), assignee, pole_ids, u.email)
    return _assignment_rows(db, project_id)


@router.post("/api/projects/{project_id}/presence")
def heartbeat_presence(project_id: str, body: PresenceIn, u: User = Depends(require_permission("project.read")), db: Session = Depends(get_db)):
    _project(db, project_id)
    now = datetime.now(timezone.utc)
    db.query(PolePresence).filter(PolePresence.last_seen < now - PRESENCE_RETENTION).delete(synchronize_session=False)
    mine = db.query(PolePresence).filter_by(project_id=project_id, user_email=u.email)
    if body.pole_internal_id is None:
        mine.delete(synchronize_session=False)
        db.commit()
    else:
        row = mine.first()
        if row:
            row.pole_internal_id, row.last_seen = body.pole_internal_id, now
            db.commit()
        else:
            db.add(PolePresence(project_id=project_id, user_email=u.email, pole_internal_id=body.pole_internal_id, last_seen=now))
            try:
                db.commit()
            except IntegrityError:  # the same person's other tab inserted first
                db.rollback()
                mine.update({PolePresence.pole_internal_id: body.pole_internal_id, PolePresence.last_seen: now}, synchronize_session=False)
                db.commit()
    hidden = hidden_authors(db, u)
    rows = (db.query(PolePresence, User).outerjoin(User, User.email == PolePresence.user_email)
            .filter(PolePresence.project_id == project_id, PolePresence.user_email != u.email,
                    PolePresence.pole_internal_id.isnot(None),
                    PolePresence.last_seen >= now - timedelta(seconds=PRESENCE_ACTIVE_SECONDS)).all())
    return [{"pole_internal_id": p.pole_internal_id, "username": display_name(user, p.user_email)}
            for p, user in rows if p.user_email not in hidden]


def _day(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


@router.get("/api/projects/{project_id}/team-progress")
def team_progress(project_id: str, days: int = Query(14, ge=1, le=90), u: User = Depends(require_permission("work.view_all")), db: Session = Depends(get_db)):
    production, qc = dataset_pair(db, _project(db, project_id))
    if not production:
        raise HTTPException(409, "Team progress is available for Production datasets")
    today = datetime.now(timezone.utc).date()
    day_list = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    since = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=timezone.utc)

    users = {user.email: user for user in db.query(User).all()}
    stats: dict[str, dict] = defaultdict(lambda: {"assigned": 0, "completed_total": 0, "completed_by_day": defaultdict(int),
                                                  "points_by_day": defaultdict(int), "edits": 0, "qc_checked": 0, "qc_failed": 0,
                                                  "last_active": None})

    def touch(email: str, when: datetime | None):
        iso = iso_utc(when)
        if iso and (stats[email]["last_active"] is None or iso > stats[email]["last_active"]):
            stats[email]["last_active"] = iso

    for assignment, user in (db.query(PoleAssignment, User).join(User, User.id == PoleAssignment.user_id)
                             .filter(PoleAssignment.project_id == production.id).all()):
        stats[user.email]["assigned"] += 1

    # A pole is complete once it has a base and a top point; credit whoever saved the later of the two.
    by_pole: dict[int, dict] = defaultdict(lambda: {"base": None, "top": None})
    pole_points = [row for row in db.query(ProductionAnnotation).filter_by(project_id=production.id).all()
                   if row.pole_internal_id is not None and (row.feature_type in POLE_BASE or row.feature_type in POLE_TOP)]
    # Timestamps can tie (coarse clocks), so the audit row id of each creation breaks ties in true save order.
    created_seq = {entity_id: audit_id for audit_id, entity_id in db.query(AuditLog.id, AuditLog.entity_id).filter(
        AuditLog.action == "CREATE_PRODUCTION_ANNOTATION", AuditLog.entity_id.in_([row.id for row in pole_points])).all()} if pole_points else {}

    def saved_order(row: ProductionAnnotation):
        return (row.created_at, created_seq.get(row.id, 0))

    for row in pole_points:
        kind = "base" if row.feature_type in POLE_BASE else "top"
        current = by_pole[row.pole_internal_id][kind]
        if current is None or saved_order(row) < saved_order(current):
            by_pole[row.pole_internal_id][kind] = row
    pole_numbers = {pole.internal_id: normalize_pole_number(pole.pole_number) for pole in db.query(Pole).filter_by(project_id=production.id).all()}
    qc_poles: set[str] = set()
    qc_failed: set[str] = set()
    if qc:
        qc_poles = {normalize_pole_number(number) for (number,) in db.query(Pole.pole_number).filter_by(project_id=qc.id).all() if number}
        qc_failed = {normalize_pole_number(number) for (number,) in db.query(Finding.pole_number)
                     .filter(Finding.project_id == qc.id, Finding.severity == "FAIL").all() if number}
    for pole_id, points in by_pole.items():
        if not (points["base"] and points["top"]):
            continue
        finisher = max(points["base"], points["top"], key=saved_order)
        entry = stats[finisher.created_by]
        entry["completed_total"] += 1
        day = _day(finisher.created_at)
        if day in day_list:
            entry["completed_by_day"][day] += 1
        number = pole_numbers.get(pole_id)
        if number and number in qc_poles:
            entry["qc_checked"] += 1
            entry["qc_failed"] += number in qc_failed

    # Activity in the period comes from the audit log, so points later deleted still count as work done.
    for entry in (db.query(AuditLog).filter(AuditLog.action.in_(["CREATE_PRODUCTION_ANNOTATION", "UPDATE_PRODUCTION_ANNOTATION", "RESTORE_PRODUCTION_ANNOTATION"]),
                                             AuditLog.created_at >= since).all()):
        try:
            detail = json.loads(entry.detail_json or "{}")
        except ValueError:
            continue
        project_of = detail.get("project_id") or (detail.get("before") or {}).get("project_id")
        if project_of != production.id:
            continue
        if entry.action == "CREATE_PRODUCTION_ANNOTATION":
            day = _day(entry.created_at)
            if day in day_list:
                stats[entry.actor]["points_by_day"][day] += 1
        else:
            stats[entry.actor]["edits"] += 1
        touch(entry.actor, entry.created_at)

    for user in users.values():
        if user.is_active and (user.role or "").upper() == "USER":
            stats[user.email]  # every active user appears, even with no work yet
    out = []
    for email, entry in stats.items():
        user = users.get(email)
        checked = entry["qc_checked"]
        out.append({
            "email": email, "username": display_name(user, email), "name": user.name if user else email,
            "role": user.role if user else None, "active": bool(user.is_active) if user else False,
            "assigned": entry["assigned"], "completed_total": entry["completed_total"],
            "completed_by_day": [entry["completed_by_day"].get(day, 0) for day in day_list],
            "completed_period": sum(entry["completed_by_day"].values()),
            "points_by_day": [entry["points_by_day"].get(day, 0) for day in day_list],
            "points_period": sum(entry["points_by_day"].values()), "edits_period": entry["edits"],
            "qc_checked": checked, "qc_failed": entry["qc_failed"],
            "qc_fail_rate": round(entry["qc_failed"] / checked, 4) if checked else None,
            "last_active": entry["last_active"],
        })
    out.sort(key=lambda row: (-row["completed_period"], -row["points_period"], row["username"].lower()))
    poles_total = len(pole_numbers)
    return {
        "production": {"id": production.id, "name": production.name}, "qc": {"id": qc.id, "name": qc.name} if qc else None,
        "days": day_list, "poles_total": poles_total,
        "poles_completed": sum(1 for points in by_pole.values() if points["base"] and points["top"]),
        "poles_assigned": sum(row["assigned"] for row in out), "users": out,
    }
