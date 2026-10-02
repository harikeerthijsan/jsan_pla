"""Add auditable Production LiDAR point annotations.

Revision ID: 20261001_0002
Revises: 20260930_0001
"""

from alembic import op

from app.db import Base
from app import models as _models  # noqa: F401


revision = '20261001_0002'
down_revision = '20260930_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables['production_annotations'].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Preserve customer annotations during application rollback.
    pass
