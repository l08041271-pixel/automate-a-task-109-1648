"""Regression tests for timezone handling across SQLite and PostgreSQL.

SQLite has no native timestamptz and SQLAlchemy hands back *naive* datetimes.
Comparing one of those with an aware ``datetime.now(UTC)`` raised
``TypeError: can't compare offset-naive and offset-aware datetimes``, which
broke booking confirmation and reminder scheduling. ``UTCDateTime`` normalises
both directions; these tests lock that behaviour in.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.enums import BookingStatus, LeadSource, PipelineStage
from app.db.models import Booking, Contact, FollowUpJob, Lead
from app.db.session import SessionLocal


class _Row:
    """Stand-in carrying only what the helper needs."""

    def __init__(self, dt):
        self.dt = dt


def test_datetimes_read_back_from_the_database_are_utc_aware():
    with SessionLocal() as db:
        contact = Contact(wa_id="966500000555", phone_e164="+966500000555")
        db.add(contact)
        db.flush()
        lead = Lead(
            contact_id=contact.id,
            source=LeadSource.WHATSAPP_INBOUND,
            initial_inquiry="hello",
            stage=PipelineStage.NEW,
            preferred_time_at=datetime(2030, 1, 1, 18, 0, tzinfo=UTC),
        )
        db.add(lead)
        db.flush()
        db.commit()

        reloaded = db.execute(select(Lead).where(Lead.id == lead.id)).scalars().one()
        assert reloaded.created_at.tzinfo is not None, "created_at came back naive"
        assert reloaded.preferred_time_at.tzinfo is not None
        # The whole point: comparing with an aware 'now' must not raise.
        assert (datetime.now(UTC) - reloaded.created_at) < timedelta(minutes=5)


def test_naive_input_is_stored_as_utc_aware():
    with SessionLocal() as db:
        contact = Contact(wa_id="966500000666", phone_e164="+966500000666")
        db.add(contact)
        db.flush()
        booking = Booking(
            contact_id=contact.id,
            status=BookingStatus.REQUESTED,
            requested_time_at=datetime(2030, 1, 1, 18, 0),  # deliberately naive
        )
        db.add(booking)
        db.flush()
        db.commit()

        reloaded = db.execute(select(Booking).where(Booking.id == booking.id)).scalars().one()
        assert reloaded.requested_time_at.tzinfo is not None
        assert (reloaded.requested_time_at - datetime.now(UTC)) > timedelta(days=1)


def test_follow_up_due_at_comparison_works_after_a_db_round_trip():
    """The exact crash path: a job loaded from the DB compared against 'now'."""
    from app.db.enums import JobStatus, JobType

    with SessionLocal() as db:
        contact = Contact(wa_id="966500000777", phone_e164="+966500000777")
        db.add(contact)
        db.flush()
        lead = Lead(contact_id=contact.id, source=LeadSource.WHATSAPP_INBOUND)
        db.add(lead)
        db.flush()
        db.add(
            FollowUpJob(
                lead_id=lead.id,
                job_type=JobType.UNANSWERED_INQUIRY,
                status=JobStatus.SCHEDULED,
                due_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        db.commit()

        job = db.execute(select(FollowUpJob)).scalars().one()
        assert job.due_at.tzinfo is not None
        assert job.due_at <= datetime.now(UTC)  # must not raise
