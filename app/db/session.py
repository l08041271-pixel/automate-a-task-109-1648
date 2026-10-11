"""Engine / session factory and FastAPI dependency.

Works with SQLite (dev on Termux) and PostgreSQL (Supabase, production)
without code changes — only ``DATABASE_URL`` differs.
"""
from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# --- Engine ---------------------------------------------------------------
if settings.is_sqlite:
    engine: Engine = create_engine(
        settings.database_url,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # enforce FKs on SQLite
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()
else:
    engine = create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,      # survives Supabase idle-connection drops
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts / background jobs."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables from the ORM metadata.

    Used for dev/test and as a bootstrap. In production prefer the reviewed
    SQL migrations in ``migrations/`` (which also add Row Level Security).
    """
    from app.db import models  # noqa: F401  (populate metadata)

    models.Base.metadata.create_all(bind=engine)
