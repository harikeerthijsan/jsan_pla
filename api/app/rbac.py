from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException

from .auth import current_user
from .models import User


ROLE_PERMISSIONS = {
    "ADMIN": {
        "workspace.delivery", "workspace.qc", "project.read", "project.create",
        "upload.create", "processing.run", "analysis.run", "finding.review", "correction.create",
        "correction.resolve", "version.create", "version.approve", "user.manage",
    },
    "PROGRAM_MANAGER": {
        "workspace.delivery", "workspace.qc", "project.read", "project.create",
        "upload.create", "processing.run", "analysis.run", "finding.review", "correction.create",
        "correction.resolve", "version.create", "version.approve",
    },
    "DELIVERY_MANAGER": {
        "workspace.delivery", "project.read", "project.create", "upload.create",
        "processing.run", "correction.resolve", "version.create",
    },
    "DELIVERY_USER": {
        "workspace.delivery", "project.read", "upload.create", "processing.run",
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


def normalize_role(role: str | None) -> str:
    return (role or "").strip().upper()


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
    if has_permission(user, "workspace.delivery"):
        out.append("DELIVERY")
    if has_permission(user, "workspace.qc"):
        out.append("QC")
    return out
