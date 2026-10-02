from pathlib import Path

from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select

from app.db import Base, initialize_schema
from app.models import Project


HEAD = '20261002_0004'


def revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_fresh_database_upgrades_to_head(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    initialize_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert {'projects', 'dataset_versions', 'processing_leases', 'production_annotations', 'alembic_version'} <= tables
    assert {'latitude', 'longitude', 'pole_internal_id'} <= {column['name'] for column in inspect(engine).get_columns('production_annotations')}
    assert {'verified_lat', 'verified_lon', 'verified_x', 'verified_y', 'verified_z'} <= {column['name'] for column in inspect(engine).get_columns('poles')}
    assert {'verified_bottom_elevation', 'verified_top_elevation', 'verified_height'} <= {column['name'] for column in inspect(engine).get_columns('poles')}
    assert revision(engine) == HEAD


def test_legacy_database_is_adopted_without_losing_rows(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Project.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(Project.__table__.insert().values(id='legacy', name='Legacy project'))

    initialize_schema(engine)

    with engine.connect() as connection:
        project_id = connection.execute(select(Project.id)).scalar_one()
    assert project_id == 'legacy'
    assert 'dataset_versions' in inspect(engine).get_table_names()
    assert revision(engine) == HEAD


def test_repeated_upgrade_is_idempotent(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'repeat.db'}")

    initialize_schema(engine)
    initialize_schema(engine)

    assert revision(engine) == HEAD
