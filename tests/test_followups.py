"""Follow-up automation tests (Phase 5).

These assert the guard-rails, not just the happy path:
consent, opt-out, cooldown, daily cap, idempotency, and "never auto-send".
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.enums import (
    ConsentStatus,
    JobStatus,
    JobType,
    LeadSource,
    MessageDirection,
    MessageStatus,
    PipelineStage,
)
from app.db.models import Contact, Conversation, FollowUpJob, Lead, Message
from app.db.session import SessionLocal
from app.services import followups


def _now() -> datetime:
    return datetime.now(UTC)


def _make_contact_lead(consent: ConsentStatus = ConsentStatus.GRANTED):
    """Create contact + WhatsApp conversation + lead; return their ids."""
    with SessionLocal() as db:
        contact = Contact(
            wa_id="966500000222", phone_e164="+966500000222", consent_status=consent
        )
        db.add(contact)
        db.flush()
        convo = Conversation(
            contact_id=contact.id, channel="whatsapp", wa_conversation_id="966500000222"
        )
        db.add(convo)
        db.flush()
        lead = Lead(
            contact_id=contact.id,
            source=LeadSource.WHATSAPP_INBOUND,
            initial_inquiry="hello",
            stage=PipelineStage.NEW,
            consent_status=consent,
            missing_info=["the requested service"],
        )
        db.add(lead)
        db.flush()
        db.commit()
        return str(contact.id), str(convo.id), str(lead.id)


def _schedule(lead_id: str, *, due_in_minutes: int = -1, key: str | None = None):
    with SessionLocal() as db:
        lead = db.get(Lead, uuid.UUID(lead_id))
        job = followups.schedule(
            db,
            lead,
            job_type=JobType.UNANSWERED_INQUIRY,
            due_at=_now() + timedelta(minutes=due_in_minutes),
            idempotency_key=key,
        )
        db.commit()
        return str(job.id) if job else None


def _run(limit: int = 50):
    with SessionLocal() as db:
        report = followups.process_due_jobs(db, limit=limit)
        db.commit()
        return report


def _drafted_messages():
    with SessionLocal() as db:
        return db.execute(
            select(Message).where(Message.status == MessageStatus.DRAFTED)
        ).scalars().all()


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_due_job_produces_a_draft_and_is_marked_done():
    _, _, lead_id = _make_contact_lead()
    _schedule(lead_id)
    report = _run()
    assert report.processed == 1
    assert report.drafted == 1

    drafts = _drafted_messages()
    assert len(drafts) == 1
    assert drafts[0].direction == MessageDirection.OUTBOUND
    assert drafts[0].is_automated is True

    with SessionLocal() as db:
        job = db.execute(select(FollowUpJob)).scalars().one()
    assert job.status == JobStatus.DONE
    assert job.attempts == 1


def test_nothing_is_ever_sent():
    _, _, lead_id = _make_contact_lead()
    _schedule(lead_id)
    _run()
    with SessionLocal() as db:
        statuses = db.execute(select(Message.status)).scalars().all()
    assert MessageStatus.SENT not in statuses


def test_future_jobs_are_not_processed():
    _, _, lead_id = _make_contact_lead()
    _schedule(lead_id, due_in_minutes=60)
    assert _run().processed == 0


# --------------------------------------------------------------------------- #
# Guard-rails
# --------------------------------------------------------------------------- #
def test_opted_out_contact_is_never_messaged():
    _, _, lead_id = _make_contact_lead(consent=ConsentStatus.OPTED_OUT)
    _schedule(lead_id)
    report = _run()
    assert report.drafted == 0
    assert report.cancelled == 1
    assert report.reasons["opted_out"] == 1
    assert _drafted_messages() == []

    with SessionLocal() as db:
        job = db.execute(select(FollowUpJob)).scalars().one()
    assert job.status == JobStatus.CANCELLED


def test_unknown_consent_defers_instead_of_messaging():
    _, _, lead_id = _make_contact_lead(consent=ConsentStatus.UNKNOWN)
    _schedule(lead_id)
    report = _run()
    assert report.drafted == 0
    assert report.skipped == 1
    assert report.reasons["awaiting_consent"] == 1
    assert _drafted_messages() == []

    with SessionLocal() as db:
        job = db.execute(select(FollowUpJob)).scalars().one()
    assert job.status == JobStatus.SCHEDULED      # still queued for later
    assert job.attempts == 0                       # no attempt consumed
    due_at = job.due_at if job.due_at.tzinfo else job.due_at.replace(tzinfo=UTC)
    assert due_at > _now() + timedelta(hours=1)  # pushed into the future


def test_cooldown_blocks_a_second_message():
    _, convo_id, lead_id = _make_contact_lead()
    with SessionLocal() as db:
        db.add(
            Message(
                conversation_id=uuid.UUID(convo_id),
                direction=MessageDirection.OUTBOUND,
                body="recent draft",
                status=MessageStatus.DRAFTED,
                is_automated=True,
                created_at=_now() - timedelta(minutes=5),
            )
        )
        db.commit()

    _schedule(lead_id)
    report = _run()
    assert report.drafted == 0
    assert report.reasons["cooldown"] == 1
    assert len(_drafted_messages()) == 1  # only the pre-existing one


def test_daily_cap_limits_automated_messages(monkeypatch):
    # Separate the two windows: 1h cooldown, but 2/day cap over 24h.
    monkeypatch.setattr(settings, "followup_cooldown_hours", 1)
    monkeypatch.setattr(settings, "followup_max_per_day", 2)

    _, convo_id, lead_id = _make_contact_lead()
    with SessionLocal() as db:
        for i in range(2):  # equals followup_max_per_day
            db.add(
                Message(
                    conversation_id=uuid.UUID(convo_id),
                    direction=MessageDirection.OUTBOUND,
                    body=f"draft {i}",
                    status=MessageStatus.DRAFTED,
                    is_automated=True,
                    created_at=_now() - timedelta(hours=2),  # outside cooldown, inside cap
                )
            )
        db.commit()

    _schedule(lead_id)
    report = _run()
    assert report.drafted == 0
    assert report.reasons["daily_cap_reached"] == 1


def test_scheduling_is_idempotent():
    _, _, lead_id = _make_contact_lead()
    first = _schedule(lead_id, key="unanswered:fixed")
    second = _schedule(lead_id, key="unanswered:fixed")
    assert first is not None
    assert second is None
    with SessionLocal() as db:
        assert len(db.execute(select(FollowUpJob)).scalars().all()) == 1


def test_job_fails_after_max_attempts():
    _, _, lead_id = _make_contact_lead(consent=ConsentStatus.UNKNOWN)
    job_id = _schedule(lead_id)
    with SessionLocal() as db:
        job = db.get(FollowUpJob, uuid.UUID(job_id))
        job.attempts = job.max_attempts
        job.due_at = _now() - timedelta(minutes=1)
        db.commit()

    report = _run()
    assert report.failed == 1
    with SessionLocal() as db:
        job = db.get(FollowUpJob, uuid.UUID(job_id))
    assert job.status == JobStatus.FAILED


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
def _viewer_headers() -> dict[str, str]:
    from app.core.security import create_access_token
    from app.db.enums import UserRole

    return {"Authorization": f"Bearer {create_access_token('v@massagevip.sa', UserRole.VIEWER)}"}


def test_run_endpoint_requires_authentication(client):
    assert client.post("/api/follow-ups/run").status_code == 401


def test_run_endpoint_requires_owner(client):
    assert client.post("/api/follow-ups/run", headers=_viewer_headers()).status_code == 403


def test_run_endpoint_reports_that_nothing_was_sent(client, admin_headers):
    _, _, lead_id = _make_contact_lead()
    _schedule(lead_id)
    resp = client.post("/api/follow-ups/run", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["drafted"] == 1
    assert "no message is sent" in body["note"].lower()


def test_list_follow_up_jobs_requires_auth(client, admin_headers):
    _, _, lead_id = _make_contact_lead()
    _schedule(lead_id, key="list:1")
    assert client.get("/api/follow-ups").status_code == 401
    resp = client.get("/api/follow-ups", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["job_type"] == "UNANSWERED_INQUIRY"


# --------------------------------------------------------------------------- #
# Booking -> reminder integration
# --------------------------------------------------------------------------- #
def test_confirming_a_booking_schedules_a_reminder(client, admin_headers):
    lead = client.post(
        "/api/leads",
        json={
            "source": "WHATSAPP_INBOUND",
            "name": "Sara",
            "phone": "0500000009",
            "wa_id": "966500000999",
            "service_interest": "massage",
            "location_text": "Riyadh",
            "initial_inquiry": "I want to book tonight",
            "consent_status": "GRANTED",
        },
    ).json()

    when = (_now() + timedelta(days=3)).isoformat()
    booking = client.post(
        "/api/bookings",
        json={"lead_id": lead["id"], "requested_time_at": when},
        headers=admin_headers,
    ).json()

    resp = client.patch(
        f"/api/bookings/{booking['id']}",
        json={"status": "CONFIRMED", "verified": True, "scheduled_at": when},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        job_types = db.execute(select(FollowUpJob.job_type)).scalars().all()
    assert JobType.APPOINTMENT_REMINDER in job_types
    assert JobType.UNANSWERED_INQUIRY in job_types
