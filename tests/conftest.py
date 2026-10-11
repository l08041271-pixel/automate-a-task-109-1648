"""Shared pytest fixtures.

Environment variables are set *before* importing the app so the cached
``Settings`` object picks them up. Each test runs against a throwaway
SQLite file that is recreated per test.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import uuid

# --- Configure the environment BEFORE importing the application ------------
_TMP_DB = pathlib.Path(tempfile.gettempdir()) / f"mv_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ENVIRONMENT"] = "development"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-definitely-long-enough-1234567890"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"  # avoid flakiness
os.environ["BUSINESS_CITY"] = "Riyadh"
os.environ["BCRYPT_ROUNDS"] = "4"  # keep password hashing fast in tests

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import deps  # noqa: E402
from app.db import models  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fresh_db():
    """Recreate all tables for every test so tests are order-independent."""
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    deps.general_limiter.reset()
    deps.login_limiter.reset()
    deps.webhook_limiter.reset()
    yield


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-API-Key": "test-admin-key"}
