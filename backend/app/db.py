from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# SQLite is only ever used by the test suite (see tests/conftest.py); it needs
# different pool settings and must be told that connections may cross threads,
# because the test client serves requests from a worker thread.
_engine_kwargs: dict = (
    {"connect_args": {"check_same_thread": False}}
    if _is_sqlite
    else {"pool_size": 10, "max_overflow": 20}
)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    **_engine_kwargs,
)

if _is_sqlite:
    # pysqlite emits its own implicit BEGIN in the wrong places, which breaks
    # SAVEPOINT — and the CSV importer runs every row inside one so a single
    # bad line cannot poison the whole transaction. The documented fix is to
    # take transaction control away from the driver and issue BEGIN ourselves.
    # PostgreSQL needs none of this.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_disable_implicit_begin(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _sqlite_emit_begin(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
