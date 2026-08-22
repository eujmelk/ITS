"""Creating, listing and removing environments.

Provisioning an environment is three steps: create its database, build the
schema, seed the parameters every install needs. Each is idempotent, so a
half-finished attempt can simply be retried.
"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import CONTROL_DATABASE, control_engine, dispose, engine_for, url_for
from app.models import Base, Environment
from app.services.parameters import ensure_seeded

log = logging.getLogger(__name__)

#: Lowercase, digits and underscores. Also what makes the derived database
#: name safe to interpolate into CREATE DATABASE, which cannot be
#: parameterised.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

RESERVED_KEYS = {"control", "postgres", "template0", "template1", "admin", "new"}


def database_name_for(key: str) -> str:
    return f"{settings.environment_db_prefix}{key}"


def validate_key(key: str) -> str:
    key = (key or "").strip().lower()
    if not KEY_PATTERN.match(key):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The key must start with a letter and contain only lowercase "
            "letters, digits and underscores (2–48 characters). It becomes "
            "part of a database name, so it cannot be changed later.",
        )
    if key in RESERVED_KEYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{key}' is reserved."
        )
    return key


def _database_exists(name: str) -> bool:
    if settings.database_url.startswith("sqlite"):
        return False
    with control_engine.connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar()
    return bool(found)


def _create_database(name: str) -> None:
    """CREATE DATABASE, which cannot run inside a transaction."""
    if settings.database_url.startswith("sqlite"):
        return  # a SQLite "database" is a file, created on first connect
    if _database_exists(name):
        log.info("Database %s already exists; reusing it", name)
        return
    with control_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as conn:
        # `name` is derived from a validated key, so it cannot carry anything
        # but [a-z0-9_] — CREATE DATABASE takes no bind parameters.
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    log.info("Created database %s", name)


def _build_schema(name: str) -> None:
    """Create every table, then mark the database as fully migrated.

    ``create_all`` produces exactly the schema the models describe, which is
    what ``head`` means, so stamping is honest rather than a shortcut.
    """
    engine = engine_for(name)
    Base.metadata.create_all(bind=engine)

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url_for(name))
    command.stamp(config, "head")


def provision(name_db: str) -> None:
    _create_database(name_db)
    _build_schema(name_db)

    from app.db import session_for

    session = session_for(name_db)
    try:
        added = ensure_seeded(session)
        log.info("Seeded %s parameters into %s", added, name_db)
    finally:
        session.close()


def create_environment(
    control: Session, key: str, name: str, notes: str | None = None
) -> Environment:
    key = validate_key(key)
    if control.scalar(select(Environment).where(Environment.key == key)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Environment '{key}' already exists."
        )

    database = database_name_for(key)
    provision(database)

    environment = Environment(
        key=key,
        name=name.strip() or key,
        database_name=database,
        is_active=True,
        is_default=control.scalar(select(Environment).limit(1)) is None,
        notes=notes,
    )
    control.add(environment)
    control.commit()
    control.refresh(environment)
    return environment


def delete_environment(control: Session, environment: Environment, drop_data: bool) -> None:
    """Remove an environment.

    The database is only dropped on an explicit request, and never the control
    database — which is also the first environment on an upgraded install, so
    dropping it would take the user table with it.
    """
    if environment.database_name == CONTROL_DATABASE and drop_data:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This environment shares the control database, which holds users "
            "and the environment registry. Its data cannot be dropped from "
            "here.",
        )

    remaining = control.scalar(
        select(Environment).where(Environment.id != environment.id).limit(1)
    )
    if remaining is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the only environment; there would be nowhere to work.",
        )

    database = environment.database_name
    was_default = environment.is_default
    control.delete(environment)
    control.flush()

    if was_default:
        remaining.is_default = True

    control.commit()

    if drop_data and not settings.database_url.startswith("sqlite"):
        dispose(database)
        with control_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            # Sessions elsewhere would block the drop; end them first.
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        log.warning("Dropped database %s", database)


def ensure_default(control: Session) -> Environment:
    """Register the control database as an environment on first startup.

    This is what makes upgrading a single-database install free: the data is
    already there, it simply gains a name.
    """
    existing = control.scalar(select(Environment).order_by(Environment.id))
    if existing is not None:
        if not control.scalar(select(Environment).where(Environment.is_default.is_(True))):
            existing.is_default = True
            control.commit()
        return existing

    environment = Environment(
        key="default",
        name=settings.app_name,
        database_name=CONTROL_DATABASE,
        is_active=True,
        is_default=True,
        notes="Created automatically from the existing database.",
    )
    control.add(environment)
    control.commit()
    control.refresh(environment)
    log.warning(
        "Registered the existing database '%s' as environment 'default'.",
        CONTROL_DATABASE,
    )
    return environment
