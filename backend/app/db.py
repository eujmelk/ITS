"""Database connections, one per environment.

An *environment* is a city or operation with its own database: `its_city1`,
`its_city2`. Isolation comes from the database rather than from a filter every
query has to remember, so the models and every query in the application are
unchanged by multi-tenancy — they simply run against whichever connection this
module hands them.

Two kinds of connection:

* the **control** database, named by ``DATABASE_URL``. It holds ``users`` and
  ``environments``: things that are shared across every city.
* an **environment** database, one per row in ``environments``. All planning
  data lives here.

Deliberately, every database gets the *whole* schema, including the ``users``
and ``environments`` tables. Those are simply unused in an environment
database. Splitting the metadata in two would mean two migration trees to keep
in step for the sake of two unread tables — and it lets the control database
double as the first environment, so an existing single-database install keeps
working with no data migration at all.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")


def _engine_kwargs(control: bool) -> dict:
    if _is_sqlite:
        return {"connect_args": {"check_same_thread": False}}
    # Environment pools are smaller: a server with a dozen cities would
    # otherwise reserve more connections than PostgreSQL allows by default.
    return (
        {"pool_size": 10, "max_overflow": 20}
        if control
        else {"pool_size": 5, "max_overflow": 10}
    )


def _tune(engine: Engine) -> Engine:
    if _is_sqlite:
        # pysqlite emits its own implicit BEGIN in the wrong places, which
        # breaks SAVEPOINT — and the CSV importer runs every row inside one so
        # a single bad line cannot poison the whole transaction. The documented
        # fix is to take transaction control away from the driver.
        @event.listens_for(engine, "connect")
        def _disable_implicit_begin(dbapi_connection, _record):  # noqa: ANN001
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _emit_begin(conn):  # noqa: ANN001
            conn.exec_driver_sql("BEGIN")
    return engine


control_engine = _tune(
    create_engine(
        settings.database_url, pool_pre_ping=True, future=True, **_engine_kwargs(True)
    )
)
ControlSession = sessionmaker(
    bind=control_engine, autoflush=False, autocommit=False, future=True
)

#: The database name `DATABASE_URL` points at. The bootstrap registers this as
#: the first environment, so upgrading a single-database install is a no-op.
CONTROL_DATABASE = make_url(settings.database_url).database or ""

_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def url_for(database: str) -> str:
    """The control URL with its database name swapped."""
    return make_url(settings.database_url).set(database=database).render_as_string(
        hide_password=False
    )


def engine_for(database: str) -> Engine:
    """Cached engine for one environment's database."""
    if database == CONTROL_DATABASE:
        return control_engine
    with _lock:
        existing = _engines.get(database)
        if existing is None:
            existing = _tune(
                create_engine(
                    url_for(database),
                    pool_pre_ping=True,
                    future=True,
                    **_engine_kwargs(False),
                )
            )
            _engines[database] = existing
        return existing


def session_for(database: str) -> Session:
    return sessionmaker(
        bind=engine_for(database), autoflush=False, autocommit=False, future=True
    )()


def dispose(database: str) -> None:
    """Drop a cached engine, e.g. after deleting its database."""
    with _lock:
        engine = _engines.pop(database, None)
    if engine is not None:
        engine.dispose()


def get_control_db() -> Iterator[Session]:
    """Session on the control database: users and the environment registry."""
    db = ControlSession()
    try:
        yield db
    finally:
        db.close()


# Kept so the many modules that import `engine` for metadata work still do.
engine = control_engine
