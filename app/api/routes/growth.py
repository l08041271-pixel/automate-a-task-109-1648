"""Growth agent endpoints. Analysis is recommendation-only; actions need approval."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, require_owner
from app.core.security import Principal
from app.db.models import AutomationRun
from app.services import growth_agent, marketing
from app.services.audit import write_audit

router = APIRouter(prefix="/growth", tags=["growth"])


class AuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=4, max_length=64)
    action_type: str = Field(min_length=3, max_length=80)
    approved: bool
    note: str | None = Field(None, max_length=500)


class AuthorizationResponse(BaseModel):
    recorded: bool
    approved: bool
    action_type: str
    recommendation_id: str
    message: str


class AutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    metrics: dict | None
    recommendations: list | None
    error: str | None


@router.post("/run")
def run_analysis(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_owner),
) -> dict:
    """Analyse metrics and return recommendations. Executes nothing."""
    report = growth_agent.run_analysis(db, days=days)
    write_audit(
        db,
        actor=principal.subject,
        action="growth_analysis_run",
        entity_type="automation_run",
        entity_id=report.run_id,
        after={"recommendations": len(report.recommendations), "mode": report.mode},
    )
    db.commit()
    return report.as_dict()


@router.get("/reports", response_model=list[AutomationRunRead])
def list_reports(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> list[AutomationRunRead]:
    rows = db.execute(
        select(AutomationRun)
        .where(AutomationRun.run_type == "growth_analysis")
        .order_by(AutomationRun.started_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        AutomationRunRead(
            id=r.id, run_type=r.run_type,
            status=r.status.value if hasattr(r.status, "value") else str(r.status),
            started_at=r.started_at, finished_at=r.finished_at, duration_ms=r.duration_ms,
            metrics=r.metrics, recommendations=r.recommendations, error=r.error,
        )
        for r in rows
    ]


@router.get("/marketing-drafts")
def marketing_drafts(
    campaign_name: str = Query("always-on", min_length=1, max_length=80),
    _: Principal = Depends(get_principal),
) -> dict:
    """Return draft content for review. Nothing is published by this endpoint."""
    drafts = marketing.build_drafts(campaign_name=campaign_name)
    return {
        "drafts": [d.as_dict() for d in drafts],
        "published": False,
        "note": (
            "Drafts only. Publishing requires connected accounts, granted "
            "permissions and explicit approval per platform."
        ),
    }


@router.post("/authorizations", response_model=AuthorizationResponse)
def authorize_action(
    payload: AuthorizationRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_owner),
) -> AuthorizationResponse:
    """Record an explicit owner authorisation for a consequential action.

    This endpoint does NOT perform the action. It creates the audit trail that
    a human (or a purpose-built job) must have before spending money,
    publishing content, deleting records or changing messaging policy.
    """
    write_audit(
        db,
        actor=principal.subject,
        action="growth_action_authorized" if payload.approved else "growth_action_rejected",
        entity_type="growth_recommendation",
        entity_id=payload.recommendation_id,
        after={"action_type": payload.action_type, "approved": payload.approved,
               "note": payload.note},
    )
    db.commit()
    return AuthorizationResponse(
        recorded=True,
        approved=payload.approved,
        action_type=payload.action_type,
        recommendation_id=payload.recommendation_id,
        message=(
            "Authorisation recorded. This endpoint did not perform the action; the "
            "action must be carried out deliberately and is now auditable."
        ),
    )
