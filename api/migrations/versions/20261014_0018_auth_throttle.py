"""Shared sign-in throttles: failed logins and email-code requests counted in the database, so every API process and
replica enforces the same limits (they used to be per-process memory).

Revision ID: 20261014_0018
Revises: 20261014_0017
"""

import sqlalchemy as sa
from alembic import op


revision = "20261014_0018"
down_revision = "20261014_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "auth_throttle_events" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "auth_throttle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
    )
    op.create_index("ix_auth_throttle_events_key_at", "auth_throttle_events", ["key", "at"])


def downgrade() -> None:
    # Older releases ignore the table; the rows age out on their own.
    pass
