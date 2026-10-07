"""Last sign-in time, address and (when the person shares it) browser location.

Revision ID: 20261007_0012
Revises: 20261007_0011
"""

import sqlalchemy as sa
from alembic import op


revision = "20261007_0012"
down_revision = "20261007_0011"
branch_labels = None
depends_on = None

COLUMNS = [
    ("last_login_at", sa.DateTime(timezone=True)),
    ("last_login_ip", sa.String(length=64)),
    ("last_login_location_status", sa.String(length=20)),
    ("last_login_latitude", sa.Float()),
    ("last_login_longitude", sa.Float()),
    ("last_login_accuracy", sa.Float()),
    ("last_login_location_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    for name, column_type in COLUMNS:
        if name not in existing:
            op.add_column("users", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    # Keep the last sign-in record during application rollback; older releases ignore these columns.
    pass
