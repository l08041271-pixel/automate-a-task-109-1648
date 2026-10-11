"""Follow-up automation endpoints (Phase 5)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, require_owner
from app.core.security import Principal
from app.db.enums import JobStatus
from app.db.models import FollowUpJob
from app.schemas.followup import FollowUpJobRead, RunReport
from app.services import followups as followups_service

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


@router.get("", response_model=list[FollowUpJobRead])
def list_jobs(
    status_filter: JobStatus | None = Query(None, alias="status"),
    lead_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> list[FollowUpJobRead]:
    stmt = select(FollowUpJob)
    if status_filter is not None:
        stmt = stmt.where(FollowUpJob.status == status_filter)
    if lead_id is not None:
        stmt = stmt.where(FollowUpJob.lead_id == lead_id)
    rows = db.execute(stmt.order_by(FollowUpJob.due_at).limit(limit)).scalars().all()
    return [FollowUpJobRead.model_validate(r) for r in rows]


@router.post("/run", response_model=RunReport)
def run_due_jobs(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_owner),
) -> RunReport:
    """Process due follow-ups. Produces DRAFTED messages only — nothing is sent."""
    report = followups_service.process_due_jobs(db, limit=limit)
    db.commit()
    return RunReport(
        processed=report.processed,
        drafted=report.drafted,
        skipped=report.skipped,
        cancelled=report.cancelled,
        failed=report.failed,
        reasons=report.reasons,
        ran_at=datetime.now().astimezone(),
    )
