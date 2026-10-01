"""Adopt or create the complete v3.4 operational schema.

Revision ID: 20260930_0001
Revises:
Create Date: 2026-09-30

This baseline is intentionally additive. Existing deployments were previously
created with SQLAlchemy ``create_all``; ``checkfirst`` adopts those tables and
creates only missing v3.4 tables before Alembic records the revision.
"""

from alembic import op

from app.db import Base
from app import models as _models  # noqa: F401
from app import workflow as _workflow  # noqa: F401


revision = '20260930_0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Customer/project data is intentionally preserved. Application rollback is
    # compatible with these additive tables; destructive downgrade is forbidden.
    pass
