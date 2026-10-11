"""Consent-aware follow-up automation.

Guarantees enforced here (and covered by tests):
  * Nothing is ever *sent*; jobs produce DRAFTED messages only.
  * A contact who opted out is never messaged again.
  * Without GRANTED consent nothing is queued (configurable, on by default).
  * A per-conversation cooldown and a per-contact daily cap prevent spam.
  * Jobs are idempotent: the same reminder cannot be queued twice.
  * Unresponsive prospects stop being contacted after ``max_attempts``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_extra
from app.db.enums import (
    ConsentStatus,
    ConversationStatus,
    JobStatus,
    JobType,
    MessageDirection,
    MessageStatus,
)
from app.db.models import Contact, Conversation, FollowUpJob, Lead, Message
from app.services import leads as leads_service
from app.services import replies as replies_service

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ProcessReport:
    processed: int = 0
    drafted: int = 0
    skipped: int = 0
    cancelled: int = 0
    failed: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def note(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def schedule(
    db: Session,
    lead: Lead,
    *,
    job_type: JobType,
    due_at: datetime,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> FollowUpJob | None:
    """Queue a follow-up. Returns ``None`` if this job already exists."""
    if idempotency_key:
        exists = db.execute(
            select(FollowUpJob).where(FollowUpJob.idempotency_key == idempotency_key)
        ).scalars().first()
        if exists is not None:
            return None

    job = FollowUpJob(
        lead_id=lead.id,
        job_type=job_type,
        status=JobStatus.SCHEDULED,
        due_at=due_at,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    leads_service.record_event(
        db, lead.id, "followup_scheduled", actor="system",
        to_value=job_type.value,
        metadata={"due_at": due_at.isoformat(), "job_id": str(job.id)},
    )
    return job


def schedule_initial_jobs(db: Session, lead: Lead) -> None:
    """Queue the standard first follow-up for a brand-new lead."""
    if lead.stage.value not in ("NEW", "CONTACTED"):
        return
    due = _now() + timedelta(hours=settings.unanswered_inquiry_hours)
    schedule(
        db, lead,
        job_type=JobType.UNANSWERED_INQUIRY,
        due_at=due,
        idempotency_key=f"unanswered:{lead.id}",
    )


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def _latest_conversation(db: Session, contact_id) -> Conversation | None:
    return db.execute(
        select(Conversation)
        .where(Conversation.contact_id == contact_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
    ).scalars().first()


def _automated_messages_since(db: Session, contact_id, since: datetime) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.contact_id == contact_id,
                Message.is_automated.is_(True),
                Message.direction == MessageDirection.OUTBOUND,
                Message.created_at >= since,
            )
        ).scalar_one()
    )


def _last_message_at(db: Session, conversation_id) -> datetime | None:
    return db.execute(
        select(func.max(Message.created_at)).where(Message.conversation_id == conversation_id)
    ).scalar()


# --------------------------------------------------------------------------- #
# Processing
# --------------------------------------------------------------------------- #
def _defer(db: Session, job: FollowUpJob, reason: str) -> None:
    """Push a job forward instead of messaging (never consumes an attempt)."""
    job.due_at = _now() + timedelta(hours=settings.followup_cooldown_hours)
    job.last_error = reason
    db.flush()


def process_due_jobs(db: Session, *, limit: int = 50) -> ProcessReport:
    """Turn due jobs into DRAFTED messages, honouring every guard-rail."""
    report = ProcessReport()
    now = _now()

    jobs = db.execute(
        select(FollowUpJob)
        .where(FollowUpJob.status == JobStatus.SCHEDULED, FollowUpJob.due_at <= now)
        .order_by(FollowUpJob.due_at)
        .limit(limit)
    ).scalars().all()

    for job in jobs:
        report.processed += 1

        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.last_error = "max_attempts_reached"
            report.failed += 1
            report.note("max_attempts_reached")
            db.flush()
            continue

        lead = db.get(Lead, job.lead_id) if job.lead_id else None
        if lead is None:
            job.status = JobStatus.CANCELLED
            job.last_error = "lead_missing"
            report.cancelled += 1
            report.note("lead_missing")
            db.flush()
            continue

        contact = db.get(Contact, lead.contact_id) if lead.contact_id else None
        if contact is None or not contact.wa_id:
            job.status = JobStatus.CANCELLED
            job.last_error = "no_whatsapp_channel"
            report.cancelled += 1
            report.note("no_whatsapp_channel")
            db.flush()
            continue

        if contact.consent_status == ConsentStatus.OPTED_OUT:
            job.status = JobStatus.CANCELLED
            job.last_error = "opted_out"
            report.cancelled += 1
            report.note("opted_out")
            db.flush()
            continue

        if settings.followup_require_consent and contact.consent_status != ConsentStatus.GRANTED:
            _defer(db, job, "awaiting_consent")
            report.skipped += 1
            report.note("awaiting_consent")
            continue

        conversation = _latest_conversation(db, contact.id)
        if conversation is None:
            job.status = JobStatus.CANCELLED
            job.last_error = "no_conversation"
            report.cancelled += 1
            report.note("no_conversation")
            db.flush()
            continue

        # --- cooldown (duplicate-message protection) ----------------------
        last_at = _last_message_at(db, conversation.id)
        cooldown = timedelta(hours=settings.followup_cooldown_hours)
        if last_at is not None:
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=UTC)
            if now - last_at < cooldown:
                _defer(db, job, "cooldown")
                report.skipped += 1
                report.note("cooldown")
                continue

        # --- daily cap ----------------------------------------------------
        sent_today = _automated_messages_since(db, contact.id, now - timedelta(hours=24))
        if sent_today >= settings.followup_max_per_day:
            _defer(db, job, "daily_cap_reached")
            report.skipped += 1
            report.note("daily_cap_reached")
            continue

        body = _render(job, lead)
        db.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.OUTBOUND,
                msg_type="text",
                body=body,
                status=MessageStatus.DRAFTED,
                is_automated=True,
            )
        )
        job.attempts += 1
        job.status = JobStatus.DONE
        job.last_error = None
        conversation.last_message_at = now
        conversation.message_count = (conversation.message_count or 0) + 1
        if conversation.status == ConversationStatus.CLOSED:
            conversation.status = ConversationStatus.OPEN

        leads_service.record_event(
            db, lead.id, "followup_drafted", actor="scheduler",
            to_value=job.job_type.value,
            metadata={"job_id": str(job.id), "sent": False},
        )
        report.drafted += 1
        db.flush()

    logger.info(
        "followups.processed",
        extra=log_extra(processed=report.processed, drafted=report.drafted,
                        skipped=report.skipped, cancelled=report.cancelled),
    )
    return report


def _render(job: FollowUpJob, lead: Lead) -> str:
    payload = dict(job.payload or {})
    scheduled = payload.get("scheduled_at")
    if scheduled:
        payload["scheduled_at_text"] = _humanise(scheduled)
    return replies_service.followup_body(
        job.job_type.value, payload=payload, missing_info=lead.missing_info
    )


def _humanise(iso_value: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return "your scheduled time"
    return dt.strftime("%a %d %b, %H:%M")
