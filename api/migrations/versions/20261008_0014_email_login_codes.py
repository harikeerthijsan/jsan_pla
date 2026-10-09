"""One-time email sign-in codes.

Revision ID: 20261008_0014
Revises: 20261008_0013
"""

import sqlalchemy as sa
from alembic import op


revision = "20261008_0014"
down_revision = "20261008_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "email_login_codes" in set(inspector.get_table_names()):
        return
    op.create_table(
        "email_login_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_email_login_codes_user_id", "email_login_codes", ["user_id"])
    op.create_index("ix_email_login_codes_created_at", "email_login_codes", ["created_at"])


def downgrade() -> None:
    # Older releases ignore this table; keep it so sign-in history is not lost on rollback.
    pass
