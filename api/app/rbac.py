from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException

from .auth import current_user
from .models import User


# Uploading LiDAR/Excel/GeoJSON and creating datasets is reserved for ADMIN. ADMIN also sees every
# user's Production work and is the only role that may edit a workbook internal_id.
ROLE_PERMISSIONS = {
    "ADMIN": {
        "workspace.production", "workspace.delivery", "workspace.qc", "project.read", "project.create",
        "upload.create", "project.delete", "processing.run", "production.annotate", "analysis.run", "finding.review", "correction.create",
        "correction.resolve", "version.create", "version.approve", "user.manage", "work.view_all",
        "workbook.edit_internal_id",
    },
    # Everything an admin can do, plus managing admin accounts and the oversight page. Super admins'
    # own work is hidden from admins and users (see team.hidden_authors).
    "SUPER_ADMIN": {
        "workspace.production", "workspace.delivery", "workspace.qc", "project.read", "project.create",
        "upload.create", "project.delete", "processing.run", "production.annotate", "analysis.run", "finding.review", "correction.create",
        "correction.resolve", "version.create", "version.approve", "user.manage", "work.view_all",
        "workbook.edit_internal_id", "user.manage_admins", "super.view",
    },
    "USER": {
        "workspace.production", "workspace.delivery", "workspace.qc", "project.read", "production.annotate",
        "analysis.run", "finding.review", "correction.create", "correction.resolve",
    },
    "PROGRAM_MANAGER": {
        "workspace.production", "workspace.delivery", "workspace.qc", "project.read",
        "processing.run", "production.annotate", "analysis.run", "finding.review", "correction.create",
        "correction.resolve", "version.create", "version.approve",
    },
    "DELIVERY_MANAGER": {
        "workspace.production", "workspace.delivery", "project.read",
        "processing.run", "production.annotate", "correction.resolve", "version.create",
    },
    "DELIVERY_USER": {
        "workspace.production", "workspace.delivery", "project.read", "processing.run", "production.annotate",
        "correction.resolve", "version.create",
    },
    "QC_LEAD": {
        "workspace.qc", "project.read", "processing.run", "analysis.run", "finding.review",
        "correction.create", "version.approve",
    },
    "QC_REVIEWER": {
        "workspace.qc", "project.read", "analysis.run", "finding.review", "correction.create",
    },
    "CUSTOMER_VIEWER": {
        "workspace.qc", "project.read",
    },
}


ADMIN_ROLES = {"ADMIN", "SUPER_ADMIN"}


def normalize_role(role: str | None) -> str:
    return (role or "").strip().upper()


def is_super_admin(user: User | None) -> bool:
    return bool(user) and normalize_role(user.role) == "SUPER_ADMIN"


def is_admin_role(role: str | None) -> bool:
    return normalize_role(role) in ADMIN_ROLES


def permissions_for(user: User) -> set[str]:
    return set(ROLE_PERMISSIONS.get(normalize_role(user.role), set()))


def has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for(user)


def require_permission(permission: str) -> Callable:
    def dependency(user: User = Depends(current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail=f"Role {user.role} is not authorized for {permission}")
        return user
    return dependency


def workspaces_for(user: User) -> list[str]:
    out = []
    if has_permission(user, "workspace.production"):
        out.append("PRODUCTION")
    if has_permission(user, "workspace.delivery"):
        out.append("DELIVERY")
    if has_permission(user, "workspace.qc"):
        out.append("QC")
    return out
