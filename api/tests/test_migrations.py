from pathlib import Path

from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select

from app.db import Base, initialize_schema
from app.models import Project


HEAD = '20260930_0001'


def revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_fresh_database_upgrades_to_head(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    initialize_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert {'projects', 'dataset_versions', 'processing_leases', 'alembic_version'} <= tables
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
