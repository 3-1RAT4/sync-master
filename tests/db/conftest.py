import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg2://sync_master:changeme@localhost:5432/mydb_test"
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def db_engine():
    """Builds the test schema by actually running the Alembic migrations
    (not Base.metadata.create_all) - some of what they do, like the `lo`
    extension and its cleanup trigger for video_files, isn't expressible as
    plain ORM metadata, so running the real migrations is what keeps this
    test schema honest about what production actually gets.
    """
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"No reachable Postgres test database at {TEST_DATABASE_URL} ({exc})")

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    try:
        command.upgrade(alembic_cfg, "head")
        yield engine
        command.downgrade(alembic_cfg, "base")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """A session whose writes (including the internal commits repository.py
    functions make) are rolled back at the end of the test, via the standard
    SQLAlchemy "join an external transaction" recipe: commits end the inner
    SAVEPOINT, which is immediately restarted, while the outer transaction is
    never actually committed.
    """
    connection = db_engine.connect()
    outer_transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()
