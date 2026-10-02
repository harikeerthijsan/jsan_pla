"""Add audited Production pole-location verification fields.

Revision ID: 20261002_0003
Revises: 20261001_0002
"""

import sqlalchemy as sa
from alembic import op


revision = "20261002_0003"
down_revision = "20261001_0002"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    annotation_columns = _columns("production_annotations")
    for column in (
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("pole_internal_id", sa.Integer(), nullable=True),
    ):
        if column.name not in annotation_columns:
            op.add_column("production_annotations", column)
    annotation_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("production_annotations")}
    if "ix_production_annotations_pole_internal_id" not in annotation_indexes:
        op.create_index("ix_production_annotations_pole_internal_id", "production_annotations", ["pole_internal_id"])

    pole_columns = _columns("poles")
    for column in (
        sa.Column("verified_lat", sa.Float(), nullable=True),
        sa.Column("verified_lon", sa.Float(), nullable=True),
        sa.Column("verified_x", sa.Float(), nullable=True),
        sa.Column("verified_y", sa.Float(), nullable=True),
        sa.Column("verified_z", sa.Float(), nullable=True),
        sa.Column("verified_block_name", sa.String(length=160), nullable=True),
        sa.Column("verified_annotation_id", sa.String(length=120), nullable=True),
        sa.Column("location_verified_by", sa.String(length=255), nullable=True),
        sa.Column("location_verified_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in pole_columns:
            op.add_column("poles", column)


def downgrade() -> None:
    # Verified customer coordinates are retained during application rollback.
    pass
