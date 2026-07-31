"""Test harness.

The tests run against SQLite rather than PostgreSQL so that `pytest` needs no
containers. Every column type in the models is portable, so this exercises the
same schema. It does *not* exercise PostgreSQL-specific behaviour (FK cascade
enforcement in particular is off by default in SQLite), so the container smoke
test in the README is still the real check.
"""

import os
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="transit-tests-"))

# Must be set before anything imports app.config, which caches its settings.
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(TEST_DIR / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-real"
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "admin-password"
os.environ["SEED_DEMO_DATA"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

API = settings.api_prefix


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client(_schema):
    # Entering the context manager runs the lifespan, which creates the
    # bootstrap admin and seeds the operating parameters.
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
