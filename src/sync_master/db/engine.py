import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to credentials.env, "
            "e.g. postgresql+psycopg2://sync_master:changeme@localhost:5432/mydb"
        )
    return url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url())
    return _engine


def get_session() -> Session:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory()


def reset_engine() -> None:
    """Drop the cached engine/session factory so a new DATABASE_URL takes effect (mainly for tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
