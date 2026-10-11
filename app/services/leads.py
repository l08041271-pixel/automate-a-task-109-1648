"""Lead lifecycle service: create, dedupe, read, update, score, timeline."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_extra
from app.db.enums import ConsentStatus, LeadSource, PipelineStage
from app.db.models import Contact, Lead, LeadEvent
from app.db.models.crm import compute_dedupe_key
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services import lead_scoring

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DuplicateLeadError(Exception):
    """Raised only when a caller explicitly requires a fresh lead."""


def _identity(wa_id: str | None, phone: str | None, email: str | None) -> str | None:
    """Strongest available identifier (WhatsApp > phone > email)."""
    return wa_id or phone or (email.lower() if email else None)


def resolve_or_create_contact(
    db: Session,
    *,
    wa_id: str | None = None,
    phone_e164: str | None = None,
    email: str | None = None,
    name: str | None = None,
    city: str | None = None,
    consent_status: ConsentStatus | None = None,
    consent_source: str | None = None,
) -> Contact | None:
    """Find the unique contact matching any provided identifier, else create one.

    Returns ``None`` when no identifying information was supplied (anonymous
    lead) so we never fabricate a contact record.
    """
    if not any((wa_id, phone_e164, email)):
        return None

    conditions = []
    if wa_id:
        conditions.append(Contact.wa_id == wa_id)
    if phone_e164:
        conditions.append(Contact.phone_e164 == phone_e164)
    if email:
        conditions.append(func.lower(Contact.email) == email.lower())

    contact = db.execute(select(Contact).where(or_(*conditions))).scalars().first()

    now = _now()
    if contact is None:
        contact = Contact(
            wa_id=wa_id,
            phone_e164=phone_e164,
            email=email.lower() if email else None,
            display_name=name,
            city=city,
            consent_status=consent_status or ConsentStatus.UNKNOWN,
            consent_source=consent_source,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(contact)
        db.flush()
        logger.info("contact.created", extra=log_extra(contact_id=str(contact.id)))
        return contact

    # Enrich, never overwrite good data with blanks.
    if phone_e164 and not contact.phone_e164:
        contact.phone_e164 = phone_e164
    if wa_id and not contact.wa_id:
        contact.wa_id = wa_id
    if email and not contact.email:
        contact.email = email.lower()
    if name and not contact.display_name:
        contact.display_name = name
    if city and not contact.city:
        contact.city = city
    if consent_status is not None:
        contact.consent_status = consent_status
        if consent_source:
            contact.consent_source = consent_source
    contact.last_seen_at = now
    db.flush()
    return contact


# --------------------------------------------------------------------------- #
# Timeline / audit helpers
# --------------------------------------------------------------------------- #
def record_event(
    db: Session,
    lead_id: uuid.UUID,
    event_type: str,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
    actor: str = "system",
    metadata: dict | None = None,
) -> LeadEvent:
    event = LeadEvent(
        lead_id=lead_id,
        event_type=event_type,
        from_value=from_value,
        to_value=to_value,
        actor=actor,
        event_metadata=metadata,
    )
    db.add(event)
    db.flush()
    return event


class SpamDetected(Exception):
    """Honeypot triggered — request is silently accepted but not stored."""


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def create_lead(
    db: Session, payload: LeadCreate, *, actor: str = "public_form"
) -> tuple[Lead, bool]:
    """Create or return an existing lead. Returns ``(lead, created)``.

    Deduplication uses a stable hash of the person's strongest identifier
    plus the lead source, enforced by a UNIQUE constraint in the database.
    """
    if payload.website:
        logger.warning("lead.spam_rejected", extra=log_extra(actor=actor))
        raise SpamDetected("honeypot field was populated")

    identity = _identity(payload.wa_id, payload.phone, payload.email)
    dedupe_key = compute_dedupe_key(identity, payload.source.value)

    if dedupe_key:
        existing = db.execute(
            select(Lead).where(Lead.dedupe_key == dedupe_key)
        ).scalars().first()
        if existing is not None:
            existing.last_activity_at = _now()
            record_event(
                db, existing.id, "duplicate_submission",
                actor=actor, metadata={"source": payload.source.value},
            )
            db.flush()
            return existing, False

    contact = resolve_or_create_contact(
        db,
        wa_id=payload.wa_id,
        phone_e164=payload.phone,
        email=str(payload.email) if payload.email else None,
        name=payload.name,
        city=payload.location_text,
        consent_status=payload.consent_status,
        consent_source=payload.consent_source,
    )

    now = _now()
    lead = Lead(
        contact_id=contact.id if contact else None,
        source=payload.source,
        source_detail=payload.source_detail,
        name=payload.name,
        phone_e164=payload.phone,
        email=str(payload.email) if payload.email else None,
        wa_id=payload.wa_id,
        initial_inquiry=payload.initial_inquiry,
        service_interest=payload.service_interest,
        preferred_time_text=payload.preferred_time_text,
        preferred_time_at=payload.preferred_time_at,
        location_text=payload.location_text,
        stage=PipelineStage.NEW,
        consent_status=payload.consent_status,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        utm_content=payload.utm_content,
        utm_term=payload.utm_term,
        dedupe_key=dedupe_key,
        last_activity_at=now,
    )
    db.add(lead)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race against a concurrent identical submission.
        db.rollback()
        existing = db.execute(
            select(Lead).where(Lead.dedupe_key == dedupe_key)
        ).scalars().first()
        if existing is None:
            raise
        return existing, False

    apply_score(db, lead, actor=actor)
    record_event(
        db, lead.id, "created", to_value=lead.stage.value, actor=actor,
        metadata={"source": lead.source.value, "classification": (
            lead.classification.value if lead.classification else None)},
    )
    logger.info("lead.created", extra=log_extra(lead_id=str(lead.id)))
    return lead, True


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def get_lead(db: Session, lead_id: uuid.UUID) -> Lead | None:
    return db.get(Lead, lead_id)


def list_leads(
    db: Session,
    *,
    stage: PipelineStage | None = None,
    classification=None,  # LeadClassification | None
    source: LeadSource | None = None,
    campaign_id: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Lead], int]:
    filters = []
    if stage is not None:
        filters.append(Lead.stage == stage)
    if classification is not None:
        filters.append(Lead.classification == classification)
    if source is not None:
        filters.append(Lead.source == source)
    if campaign_id is not None:
        filters.append(Lead.campaign_id == campaign_id)
    if since is not None:
        filters.append(Lead.created_at >= since)

    base = select(Lead).where(*filters)
    total = db.execute(
        select(func.count()).select_from(Lead).where(*filters)
    ).scalar_one()
    rows = db.execute(
        base.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return list(rows), int(total)


# --------------------------------------------------------------------------- #
# Score
# --------------------------------------------------------------------------- #
def apply_score(db: Session, lead: Lead, *, actor: str = "system") -> lead_scoring.ScoreResult:
    """(Re)compute and persist the qualification score for a lead."""
    result = lead_scoring.score_lead(lead_scoring.signals_from_lead(lead))
    previous = lead.classification.value if lead.classification else None
    lead.score = result.score
    lead.classification = result.classification
    lead.score_explanation = result.explanation()
    lead.missing_info = result.missing_info
    lead.recommended_action = result.recommended_action
    lead.scored_at = _now()
    db.flush()
    record_event(
        db, lead.id, "scored",
        from_value=previous,
        to_value=result.classification.value,
        actor=actor,
        metadata={"score": result.score, "missing_info": result.missing_info},
    )
    return result


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
class StageTransitionError(Exception):
    """Raised when an illegal pipeline transition is attempted."""


#: Fields whose change invalidates the stored score.
_SCORE_AFFECTING = {
    "service_interest", "initial_inquiry", "preferred_time_at",
    "preferred_time_text", "location_text", "name", "phone", "email", "wa_id",
    "stage", "booking_status",
}


def update_lead(
    db: Session,
    lead: Lead,
    payload: LeadUpdate,
    *,
    actor: str = "system",
    allow_stage_override: bool = False,
) -> Lead:
    from app.db.enums import PIPELINE_TRANSITIONS

    changes = payload.model_dump(exclude_unset=True)
    touched_scoring = False

    new_stage = changes.pop("stage", None)
    if new_stage is not None and new_stage != lead.stage:
        allowed = PIPELINE_TRANSITIONS.get(lead.stage, set())
        if new_stage not in allowed and not allow_stage_override:
            raise StageTransitionError(
                f"cannot move lead from {lead.stage.value} to {new_stage.value}"
            )
        record_event(
            db, lead.id, "stage_changed",
            from_value=lead.stage.value, to_value=new_stage.value, actor=actor,
        )
        lead.stage = new_stage
        touched_scoring = True

    for field, value in changes.items():
        if field == "phone":
            setattr(lead, "phone_e164", value)
            touched_scoring = True
            continue
        if getattr(lead, field, None) != value:
            setattr(lead, field, value)
            if field in _SCORE_AFFECTING:
                touched_scoring = True

    lead.last_activity_at = _now()
    db.flush()

    if touched_scoring:
        apply_score(db, lead, actor=actor)
    return lead


