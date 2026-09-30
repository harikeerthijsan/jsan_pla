import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalized_database_url() -> str:
    url = os.getenv('DATABASE_URL', 'sqlite:///./pla_qc.db')
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg://' + url[len('postgres://'):]
    elif url.startswith('postgresql://') and '+psycopg' not in url:
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    return url

DB_URL = normalized_database_url()
connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SCHEMA_INIT_LOCK_KEY = 74201934
API_ROOT = Path(__file__).resolve().parents[1]

def migration_config(connection=None) -> Config:
    config = Config(str(API_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(API_ROOT / 'migrations'))
    if connection is not None:
        config.attributes['connection'] = connection
    return config


def initialize_schema(target_engine: Engine | None = None):
    """Upgrade schema safely when API/worker/replicas start concurrently."""
    # Import model modules lazily so every mapped table is registered on Base.metadata
    # without introducing module-import cycles.
    from . import models as _models  # noqa: F401
    from . import workflow as _workflow  # noqa: F401

    schema_engine = target_engine or engine
    with schema_engine.begin() as connection:
        if schema_engine.dialect.name == 'postgresql':
            # Transaction-scoped advisory lock serializes migrations across concurrent
            # container processes/replicas. It is released automatically at commit.
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': SCHEMA_INIT_LOCK_KEY})
        command.upgrade(migration_config(connection), 'head')
