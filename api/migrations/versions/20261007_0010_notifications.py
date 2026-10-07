"""In-app notifications.

Revision ID: 20261007_0010
Revises: 20261007_0009
"""

import sqlalchemy as sa
from alembic import op


revision = "20261007_0010"
down_revision = "20261007_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "notifications" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(length=60), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("project_id", sa.String(length=80), nullable=True),
            sa.Column("pole_internal_id", sa.Integer(), nullable=True),
            sa.Column("link_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at", "created_at"])


def downgrade() -> None:
    # Keep notifications during application rollback; older releases ignore the table.
    pass
