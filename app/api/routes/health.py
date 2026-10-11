"""Health / readiness endpoints used by uptime checks and GitHub Actions."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


def _db_ok(db: Session) -> tuple[bool, str | None]:
    try:
        db.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # pragma: no cover - depends on live DB
        logger.error("health.db_check_failed: %s", exc)
        return False, str(exc)


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + dependency summary. Returns 200 unless the DB is down."""
    ok, error = _db_ok(db)
    return {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "environment": settings.environment,
        "database": "ok" if ok else "unavailable",
        "database_error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/live")
def liveness() -> dict:
    """Cheap liveness probe that does not touch the database."""
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict:
    ok, error = _db_ok(db)
    return {"ready": ok, "database_error": error}
