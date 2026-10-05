"""Link QC datasets to the Production dataset whose LiDAR they share.

Revision ID: 20261005_0006
Revises: 20261002_0005
"""

import sqlalchemy as sa
from alembic import op


revision = "20261005_0006"
down_revision = "20261002_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "source_project_id" not in {column["name"] for column in inspector.get_columns("projects")}:
        op.add_column("projects", sa.Column("source_project_id", sa.String(length=80), nullable=True))
    if "ix_projects_source_project_id" not in {index["name"] for index in inspector.get_indexes("projects")}:
        op.create_index("ix_projects_source_project_id", "projects", ["source_project_id"])


def downgrade() -> None:
    # Keep the QC dataset linkage during application rollback.
    pass
