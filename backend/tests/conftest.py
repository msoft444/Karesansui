"""pytest fixtures for Karesansui backend regression tests.

Setup (from the project root with Docker Compose already running):

    cd backend
    DATABASE_URL=postgresql://karesansui:karesansui@localhost:5432/karesansui \\
        pytest tests/ -v

Unit tests (Tests 1-4) require only a reachable PostgreSQL instance.
Integration tests (marked ``integration``) require the full stack including
a running frontend at http://localhost:3000 and backend at http://localhost:8001.
Run integration tests explicitly:

    pytest tests/ -v -m integration
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def _db_available() -> str:
    """Return DATABASE_URL; skip the entire session if DB is missing or unreachable."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip(
            "DATABASE_URL is not set. "
            "Example: DATABASE_URL=postgresql://karesansui:karesansui@localhost:5432/karesansui "
            "pytest tests/ -v"
        )
    try:
        from sqlalchemy import create_engine, text as _text

        _engine = create_engine(db_url, pool_pre_ping=True)
        with _engine.connect() as conn:
            conn.execute(_text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Database not reachable ({exc}). Is Docker Compose running?")
    return db_url


@pytest.fixture
def client(_db_available: str) -> TestClient:  # type: ignore[misc]
    """FastAPI TestClient; automatically skipped when DB is unavailable."""
    from app.main import app

    with TestClient(app) as c:
        yield c  # type: ignore[misc]
