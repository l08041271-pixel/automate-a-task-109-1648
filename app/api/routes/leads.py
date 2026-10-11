"""Lead endpoints.

POST /api/leads            public (rate-limited, honeypot-protected)
GET/PATCH/score            authenticated
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, rate_limit, require_writer
from app.core.logging import get_logger, log_extra
from app.core.security import Principal
from app.db.enums import LeadClassification, LeadSource, PipelineStage
from app.schemas.lead import (
    LeadCreate,
    LeadListResponse,
    LeadRead,
    LeadUpdate,
    ScoreResponse,
)
from app.services import leads as leads_service
from app.services.leads import SpamDetected, StageTransitionError

router = APIRouter(prefix="/leads", tags=["leads"])
logger = get_logger(__name__)


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit),
) -> LeadRead:
    """Capture a lead.

    * 201 — a new lead was created.
    * 200 — an equivalent lead already existed (idempotent de-duplication).
    * 202 — honeypot triggered; request silently accepted, nothing stored.
    """
    try:
        lead, created = leads_service.create_lead(db, payload)
    except SpamDetected:
        response.status_code = status.HTTP_202_ACCEPTED
        raise HTTPException(status_code=status.HTTP_202_ACCEPTED, detail="Received")
    db.commit()
    db.refresh(lead)
    if not created:
        response.status_code = status.HTTP_200_OK
    logger.info("lead.captured", extra=log_extra(lead_id=str(lead.id), created=created))
    return lead


@router.get("", response_model=LeadListResponse)
def list_leads(
    stage: PipelineStage | None = None,
    classification: LeadClassification | None = None,
    source: LeadSource | None = None,
    campaign_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> LeadListResponse:
    rows, total = leads_service.list_leads(
        db,
        stage=stage,
        classification=classification,
        source=source,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )
    return LeadListResponse(
        items=[LeadRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> LeadRead:
    lead = leads_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_writer),
) -> LeadRead:
    lead = leads_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    try:
        leads_service.update_lead(
            db, lead, payload,
            actor=principal.subject,
            allow_stage_override=principal.is_owner,
        )
    except StageTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/score", response_model=ScoreResponse)
def score_lead(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_writer),
) -> ScoreResponse:
    lead = leads_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    result = leads_service.apply_score(db, lead, actor=principal.subject)
    db.commit()
    return ScoreResponse(
        lead_id=lead.id,
        score=result.score,
        classification=result.classification,
        explanation=result.explanation(),
        missing_info=result.missing_info,
        recommended_action=result.recommended_action,
    )
