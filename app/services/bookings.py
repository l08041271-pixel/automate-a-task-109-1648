"""Booking lifecycle.

Hard rule enforced here AND by a database CHECK constraint: a booking can only
be CONFIRMED when ``verified`` is true, i.e. a human checked real availability.
Automated flows can request a booking but can never confirm one.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_extra
from app.db.enums import BookingStatus, PipelineStage
from app.db.models import Booking, Lead
from app.schemas.booking import BookingCreate, BookingUpdate
from app.services import leads as leads_service

logger = get_logger(__name__)


class UnverifiedConfirmationError(Exception):
    """Raised when something tries to confirm a booking without verification."""


class BookingNotFoundError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def create_booking(db: Session, payload: BookingCreate, *, actor: str = "system") -> Booking:
    lead: Lead | None = None
    if payload.lead_id is not None:
        lead = leads_service.get_lead(db, payload.lead_id)
        if lead is None:
            raise BookingNotFoundError(f"lead {payload.lead_id} not found")

    booking = Booking(
        lead_id=lead.id if lead else None,
        contact_id=lead.contact_id if lead else None,
        service=payload.service or (lead.service_interest if lead else None),
        location_text=payload.location_text or (lead.location_text if lead else None),
        requested_time_at=payload.requested_time_at or (lead.preferred_time_at if lead else None),
        duration_minutes=payload.duration_minutes,
        price_amount=payload.price_amount,
        currency=payload.currency,
        status=BookingStatus.REQUESTED,
        verified=False,  # a request is never a confirmation
    )
    db.add(booking)
    db.flush()

    if lead is not None:
        lead.booking_status = BookingStatus.REQUESTED
        lead.last_activity_at = _now()
        leads_service.record_event(
            db, lead.id, "booking_requested", actor=actor,
            to_value=BookingStatus.REQUESTED.value,
            metadata={"booking_id": str(booking.id), "verified": False},
        )
    logger.info("booking.created", extra=log_extra(booking_id=str(booking.id)))
    return booking


def update_booking(
    db: Session, booking: Booking, payload: BookingUpdate, *, actor: str = "system"
) -> Booking:
    changes = payload.model_dump(exclude_unset=True)

    new_status: BookingStatus | None = changes.get("status")
    becoming_confirmed = new_status == BookingStatus.CONFIRMED

    if "verified" in changes and changes["verified"]:
        booking.verified = True
        booking.verified_by = changes.get("verified_by") or actor
        booking.verified_at = _now()
    if changes.get("verification_notes") is not None:
        booking.verification_notes = changes["verification_notes"]

    if becoming_confirmed and not booking.verified:
        raise UnverifiedConfirmationError(
            "A booking cannot be confirmed before a human verifies availability. "
            "Set verified=true together with the confirmation."
        )

    for field in ("scheduled_at", "duration_minutes", "price_amount", "service", "location_text"):
        if field in changes and changes[field] is not None:
            setattr(booking, field, changes[field])

    previous_status = booking.status
    if new_status is not None:
        booking.status = new_status

    if becoming_confirmed and booking.scheduled_at is None:
        # Confirming without a concrete time is meaningless; fall back to the request.
        booking.scheduled_at = booking.requested_time_at

    db.flush()
    _sync_lead(db, booking, previous_status, actor)
    return booking


def _sync_lead(db: Session, booking: Booking, previous_status: BookingStatus, actor: str) -> None:
    if booking.lead_id is None:
        return
    lead = leads_service.get_lead(db, booking.lead_id)
    if lead is None:
        return

    lead.booking_status = booking.status
    lead.last_activity_at = _now()

    if booking.status == BookingStatus.CONFIRMED and previous_status != BookingStatus.CONFIRMED:
        if lead.stage in (PipelineStage.NEW, PipelineStage.CONTACTED, PipelineStage.QUALIFIED):
            leads_service.record_event(
                db, lead.id, "stage_changed",
                from_value=lead.stage.value, to_value=PipelineStage.BOOKED.value, actor=actor,
            )
            lead.stage = PipelineStage.BOOKED
        leads_service.record_event(
            db, lead.id, "booking_confirmed", actor=actor,
            to_value=BookingStatus.CONFIRMED.value,
            metadata={"booking_id": str(booking.id), "verified_by": booking.verified_by},
        )
        _schedule_reminder(db, lead, booking)

    elif booking.status == BookingStatus.COMPLETED and previous_status != BookingStatus.COMPLETED:
        if lead.stage != PipelineStage.COMPLETED:
            leads_service.record_event(
                db, lead.id, "stage_changed",
                from_value=lead.stage.value, to_value=PipelineStage.COMPLETED.value, actor=actor,
            )
            lead.stage = PipelineStage.COMPLETED
        _schedule_feedback(db, lead, booking)

    elif booking.status in (BookingStatus.CANCELLED, BookingStatus.NO_SHOW):
        leads_service.record_event(
            db, lead.id, "booking_" + booking.status.value.lower(), actor=actor,
            metadata={"booking_id": str(booking.id)},
        )

    db.flush()


def _schedule_reminder(db: Session, lead: Lead, booking: Booking) -> None:
    from datetime import timedelta

    from app.core.config import settings
    from app.db.enums import JobType
    from app.services import followups

    if booking.scheduled_at is None:
        return
    due = booking.scheduled_at - timedelta(hours=settings.appointment_reminder_hours_before)
    followups.schedule(
        db, lead,
        job_type=JobType.APPOINTMENT_REMINDER,
        due_at=max(due, _now()),
        payload={"booking_id": str(booking.id), "scheduled_at": booking.scheduled_at.isoformat()},
        idempotency_key=f"reminder:{booking.id}",
    )


def _schedule_feedback(db: Session, lead: Lead, booking: Booking) -> None:
    from datetime import timedelta

    from app.core.config import settings
    from app.db.enums import JobType
    from app.services import followups

    followups.schedule(
        db, lead,
        job_type=JobType.POST_APPOINTMENT_FEEDBACK,
        due_at=_now() + timedelta(hours=settings.feedback_delay_hours),
        payload={"booking_id": str(booking.id)},
        idempotency_key=f"feedback:{booking.id}",
    )
