"""Employee directory imported from the HR export, linkable to application accounts.

Revision ID: 20261009_0016
Revises: 20261008_0015
"""

import sqlalchemy as sa
from alembic import op


revision = "20261009_0016"
down_revision = "20261008_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "employee_directory" in set(inspector.get_table_names()):
        return
    op.create_table(
        "employee_directory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("jsan_id", sa.String(length=80), nullable=True),
        sa.Column("employee_id", sa.String(length=80), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("designation", sa.String(length=160), nullable=True),
        sa.Column("date_of_joining", sa.Date(), nullable=True),
        sa.Column("experience_years", sa.Float(), nullable=True),
        sa.Column("source_role", sa.String(length=40), nullable=True),
        sa.Column("source_password_set", sa.Boolean(), nullable=True),
        sa.Column("source_last_sign_in", sa.Date(), nullable=True),
        sa.Column("submission_status", sa.String(length=40), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_employee_directory_email", "employee_directory", ["email"], unique=True)
    op.create_index("ix_employee_directory_jsan_id", "employee_directory", ["jsan_id"], unique=True)
    op.create_index("ix_employee_directory_user_id", "employee_directory", ["user_id"], unique=True)


def downgrade() -> None:
    # Older releases ignore this table; keep the imported directory on rollback.
    pass
