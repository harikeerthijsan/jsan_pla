"""Usernames and first-sign-in password change for staff accounts.

Revision ID: 20261006_0007
Revises: 20261005_0006
"""

import sqlalchemy as sa
from alembic import op


revision = "20261006_0007"
down_revision = "20261005_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "username" not in columns:
        op.add_column("users", sa.Column("username", sa.String(length=80), nullable=True))
    if "must_change_password" not in columns:
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "ix_users_username" not in {index["name"] for index in inspector.get_indexes("users")}:
        op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    # Keep account names and the password-change flag during application rollback.
    pass
