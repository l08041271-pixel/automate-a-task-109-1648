"""Analytics endpoints for the CEO dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal
from app.core.security import Principal
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(
    days: int = Query(30, ge=1, le=365, description="Rolling window in days"),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> dict:
    """Headline metrics with explicit provenance for every figure."""
    return analytics.build_summary(db, days=days)
