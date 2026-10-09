"""Super-admin oversight: everyone's work across all datasets.

Every route needs ``super.view`` (SUPER_ADMIN only). Super admins see all accounts and all activity, including
other super admins'; admins and users never reach these routes (see team.hidden_authors for their views).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Pole, PoleAssignment, Project, ProductionAnnotation, ReviewDecision, User, iso_utc
from .pipeline import dataset_pair, production_project_ids
from .rbac import require_permission
from .team import TEAM_ACTIONS, audit_project, compute_team_progress, display_name, merge_team_progress

router = APIRouter()

ACTION_GROUPS = {
    "production": {"CREATE_PRODUCTION_ANNOTATION", "UPDATE_PRODUCTION_ANNOTATION", "DELETE_PRODUCTION_ANNOTATION",
                   "RESTORE_PRODUCTION_ANNOTATION", "VERIFY_POLE_LOCATION", "ASSIGN_POLES", "UPDATE_PRODUCTION_WORKBOOK"},
    "qc": {"FINDING_DECISION", "REQUEST_CORRECTION", "RESOLVE_CORRECTION", "QUEUE_SECTION", "GENERATE_SECTION",
           "QUEUE_PROCESSING", "PROCESS_DATASET", "CREATE_QC_DATASET"},
    "data": {"CREATE_PROJECT", "QUEUE_LIDAR_PROCESSING", "PROCESS_LIDAR", "REPLACE_PRODUCTION_WORKBOOK",
             "REJECT_PRODUCTION_WORKBOOK", "CREATE_DATASET_REVISION", "BASELINE_DATASET_VERSION"},
    "delivery": {"APPROVE_DATASET_VERSION", "BUILD_DELIVERABLE_PACKAGE", "DOWNLOAD_DELIVERABLE_PACKAGE"},
    "accounts": {"CREATE_USER", "UPDATE_USER", "CHANGE_ROLE", "DEACTIVATE_USER", "REACTIVATE_USER", "ALLOW_REMOTE_ACCESS",
                 "REVOKE_REMOTE_ACCESS", "UPDATE_NETWORK_POLICY", "CHANGE_OWN_PASSWORD", "UPDATE_OWN_PROFILE",
                 "PROMOTE_SUPER_ADMIN", "SEED_STAFF_ACCOUNT", "LOGIN_BLOCKED_NETWORK", "RESET_PASSWORD",
                 "IMPORT_EMPLOYEE_DIRECTORY", "CREATE_EMPLOYEE", "UPDATE_EMPLOYEE", "DELETE_EMPLOYEE", "GRANT_EMPLOYEE_ACCESS",
                 "LINK_EMPLOYEE_ACCOUNT"},
}
GROUP_OF = {action: group for group, actions in ACTION_GROUPS.items() for action in actions}
LABELS = {
    "CREATE_PRODUCTION_ANNOTATION": "Saved a point", "UPDATE_PRODUCTION_ANNOTATION": "Edited a point",
    "DELETE_PRODUCTION_ANNOTATION": "Deleted a point", "RESTORE_PRODUCTION_ANNOTATION": "Restored a point",
    "VERIFY_POLE_LOCATION": "Verified a pole location", "ASSIGN_POLES": "Assigned poles", "UPDATE_PRODUCTION_WORKBOOK": "Edited workbook data",
    "FINDING_DECISION": "Reviewed a QC finding", "REQUEST_CORRECTION": "Requested a correction", "RESOLVE_CORRECTION": "Resolved a correction",
    "QUEUE_SECTION": "Requested a profile", "GENERATE_SECTION": "Generated a profile", "QUEUE_PROCESSING": "Started QC processing",
    "PROCESS_DATASET": "QC processing finished", "CREATE_QC_DATASET": "Created a QC dataset", "CREATE_PROJECT": "Created a dataset",
    "QUEUE_LIDAR_PROCESSING": "Started LiDAR import", "PROCESS_LIDAR": "LiDAR import finished", "REPLACE_PRODUCTION_WORKBOOK": "Replaced the Excel",
    "REJECT_PRODUCTION_WORKBOOK": "Excel replacement rejected", "CREATE_DATASET_REVISION": "Created a dataset revision",
    "BASELINE_DATASET_VERSION": "Baselined a dataset version", "APPROVE_DATASET_VERSION": "Approved a dataset version",
    "BUILD_DELIVERABLE_PACKAGE": "Built a deliverable package", "DOWNLOAD_DELIVERABLE_PACKAGE": "Downloaded a deliverable package",
    "CREATE_USER": "Created an account", "RESET_PASSWORD": "Reset a password",
    "IMPORT_EMPLOYEE_DIRECTORY": "Imported the employee directory", "CREATE_EMPLOYEE": "Added an employee",
    "UPDATE_EMPLOYEE": "Edited an employee", "DELETE_EMPLOYEE": "Removed an employee", "GRANT_EMPLOYEE_ACCESS": "Gave an employee access",
    "LINK_EMPLOYEE_ACCOUNT": "Linked an employee to an account", "UPDATE_USER": "Updated an account", "CHANGE_ROLE": "Changed a role",
    "DEACTIVATE_USER": "Deactivated an account", "REACTIVATE_USER": "Reactivated an account",
    "ALLOW_REMOTE_ACCESS": "Allowed access from anywhere", "REVOKE_REMOTE_ACCESS": "Limited access to the office",
    "UPDATE_NETWORK_POLICY": "Changed office networks", "CHANGE_OWN_PASSWORD": "Changed own password",
    "UPDATE_OWN_PROFILE": "Updated own profile", "PROMOTE_SUPER_ADMIN": "Promoted to super admin",
    "SEED_STAFF_ACCOUNT": "Staff account created", "LOGIN_BLOCKED_NETWORK": "Sign-in blocked (outside office)",
}
POINT_ACTIONS = {"CREATE_PRODUCTION_ANNOTATION"}
EDIT_ACTIONS = {"UPDATE_PRODUCTION_ANNOTATION", "RESTORE_PRODUCTION_ANNOTATION"}
SYSTEM_ACTORS = {"system", "worker"}


def _detail(entry: AuditLog) -> dict:
    try:
        value = json.loads(entry.detail_json or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _context(entry: AuditLog, detail: dict) -> tuple[str | None, int | None]:
    before = detail.get("before") if isinstance(detail.get("before"), dict) else {}
    project_id = detail.get("project_id") or before.get("project_id") or (entry.entity_id if entry.entity_type == "project" else None)
    pole = detail.get("pole_internal_id", before.get("pole_internal_id"))
    try:
        pole = int(pole) if pole is not None else None
    except (TypeError, ValueError):
        pole = None
    return project_id, pole


def _summary(entry: AuditLog, detail: dict) -> str | None:
    before = detail.get("before") if isinstance(detail.get("before"), dict) else {}
    for key in ("feature_type", "decision", "username", "role", "to"):
        value = detail.get(key) or before.get(key)
        if value:
            return str(value)[:120]
    return None


@router.get("/api/super/activity")
def activity(actor: str | None = Query(None, max_length=255), group: str | None = Query(None, pattern="^(production|qc|data|delivery|accounts|other)$"),
             project_id: str | None = Query(None, max_length=80), before_id: int | None = Query(None, ge=1),
             limit: int = Query(50, ge=1, le=200), u: User = Depends(require_permission("super.view")), db: Session = Depends(get_db)):
    """Everyone's actions, newest first. Filtering by group/project happens on decoded rows, scanning a bounded window."""
    users = {row.email: row for row in db.query(User).all()}
    projects = {row.id: row.name for row in db.query(Project.id, Project.name).all()}
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if before_id:
        query = query.filter(AuditLog.id < before_id)
    if group and group != "other":
        query = query.filter(AuditLog.action.in_(sorted(ACTION_GROUPS[group])))
    items, scanned, next_before = [], 0, None
    for entry in query.yield_per(500):
        scanned += 1
        if scanned > 20000:
            next_before = entry.id + 1
            break
        if group == "other" and entry.action in GROUP_OF:
            continue
        detail = _detail(entry)
        project, pole = _context(entry, detail)
        if project_id and project != project_id:
            continue
        person = users.get(entry.actor)
        items.append({
            "id": entry.id, "at": iso_utc(entry.created_at), "actor": entry.actor,
            "actor_name": "System" if entry.actor in SYSTEM_ACTORS else display_name(person, entry.actor),
            "actor_role": person.role if person else None, "action": entry.action,
            "label": LABELS.get(entry.action, entry.action.replace("_", " ").capitalize()),
            "group": GROUP_OF.get(entry.action, "other"), "project_id": project, "project_name": projects.get(project),
            "pole_internal_id": pole, "summary": _summary(entry, detail),
        })
        if len(items) >= limit:
            next_before = entry.id
            break
    return {"items": items, "next_before_id": next_before}


def _all_progress(db: Session, days: int) -> dict:
    """Team progress summed over every Production dataset. Accounts and the period's audit rows are read once, and
    only datasets with Production work are computed in full; pole totals for the rest come from one grouped query."""
    production_ids = production_project_ids(db)
    since = datetime.combine(datetime.now(timezone.utc).date() - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)
    users = {row.email: row for row in db.query(User).all()}
    audit_by_project: dict[str, list] = defaultdict(list)
    for entry in db.query(AuditLog).filter(AuditLog.action.in_(TEAM_ACTIONS), AuditLog.created_at >= since).all():
        project = audit_project(entry)
        if project in production_ids:
            audit_by_project[project].append(entry)
    active = ({row[0] for row in db.query(ProductionAnnotation.project_id).distinct().all()}
              | {row[0] for row in db.query(PoleAssignment.project_id).distinct().all()} | set(audit_by_project)) & production_ids
    parts = []
    for project in db.query(Project).filter(Project.id.in_(sorted(active))).order_by(Project.created_at).all():
        production, qc = dataset_pair(db, project)
        if production and production.id == project.id:
            parts.append(compute_team_progress(db, production, qc, days, set(), users=users, audit_rows=audit_by_project.get(project.id, []),
                                               include_idle=False))
    merged = merge_team_progress(parts, days)
    # Every active user appears once, even with no work yet (per-dataset parts leave idle people out).
    present = {row["email"] for row in merged["users"]}
    zeros = [0] * len(merged["days"])
    for person in users.values():
        if person.is_active and (person.role or "").upper() == "USER" and person.email not in present:
            merged["users"].append({"email": person.email, "username": display_name(person, person.email), "name": person.name,
                                    "role": person.role, "active": True, "assigned": 0, "completed_total": 0, "completed_by_day": list(zeros),
                                    "completed_period": 0, "points_by_day": list(zeros), "points_period": 0, "edits_period": 0,
                                    "qc_checked": 0, "qc_failed": 0, "qc_fail_rate": None, "last_active": None})
    datasets = db.query(Project.id, Project.name).filter(Project.id.in_(sorted(production_ids))).order_by(Project.created_at).all() if production_ids else []
    merged["datasets"] = [{"id": pid, "name": name} for pid, name in datasets]
    merged["production"] = {"id": "all", "name": f"All Production datasets ({len(datasets)})"}
    linked_qc = sum(1 for part in parts if part.get("qc"))
    merged["qc"] = {"id": "all", "name": f"{linked_qc} linked QC dataset{'' if linked_qc == 1 else 's'}"} if linked_qc else None
    merged["poles_total"] = (db.query(func.count(Pole.id)).filter(Pole.project_id.in_(sorted(production_ids))).scalar() or 0) if production_ids else 0
    return merged


@router.get("/api/super/team-progress")
def team_progress_all(days: int = Query(14, ge=1, le=90), u: User = Depends(require_permission("super.view")), db: Session = Depends(get_db)):
    return _all_progress(db, days)


@router.get("/api/super/people")
def people(days: int = Query(30, ge=1, le=365), u: User = Depends(require_permission("super.view")), db: Session = Depends(get_db)):
    """Every account (all roles) with access settings, sign-in and a summary of their work."""
    from .main import user_dict  # local import: main includes this router

    since = datetime.now(timezone.utc) - timedelta(days=days)
    period: dict[str, dict] = defaultdict(lambda: {"points": 0, "edits": 0, "deletes": 0, "qc_decisions": 0})
    for actor_email, action, count in (db.query(AuditLog.actor, AuditLog.action, func.count(AuditLog.id))
                                       .filter(AuditLog.created_at >= since).group_by(AuditLog.actor, AuditLog.action).all()):
        entry = period[actor_email]
        if action in POINT_ACTIONS: entry["points"] += count
        elif action in EDIT_ACTIONS: entry["edits"] += count
        elif action == "DELETE_PRODUCTION_ANNOTATION": entry["deletes"] += count
        elif action == "FINDING_DECISION": entry["qc_decisions"] += count
    last_active = {actor_email: when for actor_email, when in db.query(AuditLog.actor, func.max(AuditLog.created_at)).group_by(AuditLog.actor).all()}
    points_total = dict(db.query(ProductionAnnotation.created_by, func.count(ProductionAnnotation.id)).group_by(ProductionAnnotation.created_by).all())
    decisions_total = dict(db.query(ReviewDecision.reviewer_email, func.count(ReviewDecision.id)).group_by(ReviewDecision.reviewer_email).all())
    progress = _all_progress(db, min(days, 90))
    completed = {row["email"]: row["completed_total"] for row in progress["users"]}
    out = []
    for person in db.query(User).order_by(User.name, User.email).all():
        stats = period.get(person.email, {"points": 0, "edits": 0, "deletes": 0, "qc_decisions": 0})
        out.append({**user_dict(person), "days": days, "points_period": stats["points"], "edits_period": stats["edits"],
                    "deletes_period": stats["deletes"], "qc_decisions_period": stats["qc_decisions"],
                    "points_total": points_total.get(person.email, 0), "qc_decisions_total": decisions_total.get(person.email, 0),
                    "poles_completed_total": completed.get(person.email, 0), "last_active": iso_utc(last_active.get(person.email))})
    return out
