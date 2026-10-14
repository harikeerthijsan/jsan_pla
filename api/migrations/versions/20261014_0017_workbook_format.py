"""Workbook format per project: PLA-1 (single ZoneName sheet, filled by hand) or PLA-2 (COLLECTION, filled from points).

Nullable: projects created before this release are detected from their workbook on first use.

Revision ID: 20261014_0017
Revises: 20261009_0016
"""

import sqlalchemy as sa
from alembic import op


revision = "20261014_0017"
down_revision = "20261009_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "workbook_format" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("projects")}:
        op.add_column("projects", sa.Column("workbook_format", sa.String(length=10), nullable=True))


def downgrade() -> None:
    # Older releases ignore the column; keep the recorded formats.
    pass
