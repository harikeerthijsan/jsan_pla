import os
from sqlalchemy import create_engine, text
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

def initialize_schema():
    """Create additive schema safely when API/worker/replicas start concurrently."""
    # Import model modules lazily so every mapped table is registered on Base.metadata
    # without introducing module-import cycles.
    from . import models as _models  # noqa: F401
    from . import workflow as _workflow  # noqa: F401
    from . import v4_domain as _v4_domain  # noqa: F401

    if engine.dialect.name == 'postgresql':
        # Transaction-scoped advisory lock serializes DDL across concurrent
        # container processes/replicas. It is released automatically at commit.
        with engine.begin() as connection:
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': SCHEMA_INIT_LOCK_KEY})
            Base.metadata.create_all(bind=connection)
    else:
        Base.metadata.create_all(bind=engine)
