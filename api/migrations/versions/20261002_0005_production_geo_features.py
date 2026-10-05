"""Add client GeoJSON features imported for Production datasets.

Revision ID: 20261002_0005
Revises: 20261002_0004
"""

from alembic import op

from app.db import Base
from app import models as _models  # noqa: F401


revision = '20261002_0005'
down_revision = '20261002_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables['production_geo_features'].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Preserve imported client features during application rollback.
    pass
