"""Session versions, account deactivation and production point revisions.

Revision ID: 20261007_0008
Revises: 20261006_0007
"""

import sqlalchemy as sa
from alembic import op


revision = "20261007_0008"
down_revision = "20261006_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    users = {column["name"] for column in inspector.get_columns("users")}
    if "token_version" not in users:
        op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    if "is_active" not in users:
        op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    annotations = {column["name"] for column in inspector.get_columns("production_annotations")}
    if "revision" not in annotations:
        op.add_column("production_annotations", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    # Keep session versions, account status and point revisions during application rollback.
    pass
