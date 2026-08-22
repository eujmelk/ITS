"""Test harness.

Runs against **PostgreSQL**, not SQLite. Multi-environment isolation works by
giving each environment its own database, and SQLite cannot express that — so
testing on it would leave the one thing most worth testing untested.

Point ``TEST_DATABASE_URL`` at a server you do not mind losing: the suite
creates a scratch control database, drops it at the end, and drops any
environment database it provisioned along the way.

    docker compose up -d db
    cd backend
    TEST_DATABASE_URL=postgresql+psycopg://transit:transit@localhost:5432/postgres pytest

or, from inside the stack:

    docker compose run --rm api sh -c "pip install -r requirements-dev.txt && pytest"
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

#: Server to create the scratch databases on. The database named here is only
#: used to connect; it is never modified.
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://transit:transit@db:5432/postgres",
)

#: Unique per run, so two suites on one server never collide.
CONTROL_DB = f"its_test_{uuid.uuid4().hex[:10]}"


def _admin_connection():
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", future=True)
    return engine


def _drop_database(conn, name: str) -> None:
    conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :name AND pid <> pg_backend_pid()"
        ),
        {"name": name},
    )
    conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


admin_engine = _admin_connection()
with admin_engine.connect() as _conn:
    _drop_database(_conn, CONTROL_DB)
    _conn.execute(text(f'CREATE DATABASE "{CONTROL_DB}"'))

CONTROL_URL = make_url(ADMIN_URL).set(database=CONTROL_DB).render_as_string(
    hide_password=False
)

# Must be set before anything imports app.config, which caches its settings.
os.environ["DATABASE_URL"] = CONTROL_URL
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-real"
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "admin-password"
os.environ["SEED_DEMO_DATA"] = "false"
# Environment databases created by the tests share the run's unique prefix, so
# the teardown can find and drop every one of them.
os.environ["ENVIRONMENT_DB_PREFIX"] = f"{CONTROL_DB}_env_"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import control_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

API = settings.api_prefix


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=control_engine)
    yield
    control_engine.dispose()
    with admin_engine.connect() as conn:
        # Anything the environment tests provisioned, plus the control DB.
        leftovers = conn.execute(
            text("SELECT datname FROM pg_database WHERE datname LIKE :pattern"),
            {"pattern": f"{CONTROL_DB}%"},
        ).scalars().all()
        for name in leftovers:
            _drop_database(conn, name)


@pytest.fixture(scope="session")
def client(_schema):
    # Entering the context manager runs the lifespan, which creates the
    # bootstrap admin, registers the default environment and seeds the
    # operating parameters.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    response = client.post(
        f"{API}/auth/login",
        data={"username": "admin", "password": "admin-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}
