"""Add verified Production pole elevations and calculated height.

Revision ID: 20261002_0004
Revises: 20261002_0003
"""

import sqlalchemy as sa
from alembic import op


revision = "20261002_0004"
down_revision = "20261002_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("poles")}
    for column in (
        sa.Column("verified_bottom_elevation", sa.Float(), nullable=True),
        sa.Column("verified_top_elevation", sa.Float(), nullable=True),
        sa.Column("verified_height", sa.Float(), nullable=True),
        sa.Column("verified_bottom_annotation_id", sa.String(length=120), nullable=True),
        sa.Column("verified_top_annotation_id", sa.String(length=120), nullable=True),
    ):
        if column.name not in existing:
            op.add_column("poles", column)


def downgrade() -> None:
    # Verified customer measurements are retained during application rollback.
    pass
