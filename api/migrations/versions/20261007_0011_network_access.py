"""Per-user remote access and application settings (office-network policy).

Revision ID: 20261007_0011
Revises: 20261007_0010
"""

import sqlalchemy as sa
from alembic import op


revision = "20261007_0011"
down_revision = "20261007_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "remote_access" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("remote_access", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "app_settings" not in set(inspector.get_table_names()):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=80), primary_key=True),
            sa.Column("value_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    # Keep the policy and remote-access flags during application rollback; older releases ignore them.
    pass
