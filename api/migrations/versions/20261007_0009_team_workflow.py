"""Pole assignments and live pole presence.

Revision ID: 20261007_0009
Revises: 20261007_0008
"""

import sqlalchemy as sa
from alembic import op


revision = "20261007_0009"
down_revision = "20261007_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "pole_assignments" not in tables:
        op.create_table(
            "pole_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.String(length=80), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("pole_internal_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("assigned_by", sa.String(length=255), nullable=False),
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("project_id", "pole_internal_id", name="uq_pole_assignment"),
        )
        op.create_index("ix_pole_assignments_project_user", "pole_assignments", ["project_id", "user_id"])
    if "pole_presence" not in tables:
        op.create_table(
            "pole_presence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.String(length=80), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=False),
            sa.Column("pole_internal_id", sa.Integer(), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("project_id", "user_email", name="uq_pole_presence_user"),
        )
        op.create_index("ix_pole_presence_project_seen", "pole_presence", ["project_id", "last_seen"])


def downgrade() -> None:
    # Keep assignments during application rollback; older releases ignore these tables.
    pass
