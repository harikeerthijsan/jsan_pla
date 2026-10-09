"""Per-account address that receives email sign-in codes.

users.sign_in_email is separate from users.email because the account email is the identity key stored in tokens
and work records; the sign-in address can change without touching any of that.

Revision ID: 20261008_0015
Revises: 20261008_0014
"""

import sqlalchemy as sa
from alembic import op


revision = "20261008_0015"
down_revision = "20261008_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "sign_in_email" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}:
        op.add_column("users", sa.Column("sign_in_email", sa.String(length=255), nullable=True))
        op.create_index("ix_users_sign_in_email", "users", ["sign_in_email"], unique=True)


def downgrade() -> None:
    # Older releases ignore the column; keep the addresses.
    pass
