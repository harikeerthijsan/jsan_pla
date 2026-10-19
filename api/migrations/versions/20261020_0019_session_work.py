"""Session work: measurements saved per dataset, and work archives (what an admin exported, so exactly that can be cleared).

Revision ID: 20261020_0019
Revises: 20261014_0018
"""

import sqlalchemy as sa
from alembic import op


revision = "20261020_0019"
down_revision = "20261014_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "production_measurements" not in tables:
        op.create_table(
            "production_measurements",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("project_id", sa.String(length=80), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("pole_internal_id", sa.Integer(), nullable=True),
            sa.Column("ax", sa.Float(), nullable=False), sa.Column("ay", sa.Float(), nullable=False), sa.Column("az", sa.Float(), nullable=False),
            sa.Column("bx", sa.Float(), nullable=False), sa.Column("by", sa.Float(), nullable=False), sa.Column("bz", sa.Float(), nullable=False),
            sa.Column("distance", sa.Float(), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_production_measurements_project_id", "production_measurements", ["project_id"])
    if "work_archives" not in tables:
        op.create_table(
            "work_archives",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("project_id", sa.String(length=80), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("items_json", sa.Text(), nullable=False),
            sa.Column("counts_json", sa.Text(), nullable=False),
            sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cleared_by", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_work_archives_project_id", "work_archives", ["project_id"])


def downgrade() -> None:
    # Older releases ignore these tables; keep the recorded measurements and archives.
    pass
