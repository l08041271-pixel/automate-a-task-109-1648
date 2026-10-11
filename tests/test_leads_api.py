"""Integration tests for the lead API (Phase 1)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.enums import UserRole
from app.db.models import Lead, LeadEvent
from app.db.session import SessionLocal

BASE = "/api/leads"

FULL_PAYLOAD = {
    "source": "WEBSITE_FORM",
    "name": "Sara",
    "phone": "0500000001",
    "email": "sara@example.com",
    "service_interest": "home massage",
    "initial_inquiry": "I want to book an appointment",
    "preferred_time_text": "tomorrow evening",
    "location_text": "Riyadh",
    "consent_status": "GRANTED",
    "consent_source": "website_form_checkbox",
}


def _staff_headers() -> dict[str, str]:
    token = create_access_token("staff@massagevip.test", UserRole.STAFF)
    return {"Authorization": f"Bearer {token}"}


def _viewer_headers() -> dict[str, str]:
    token = create_access_token("viewer@massagevip.test", UserRole.VIEWER)
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
def test_create_lead_returns_201_and_scores_it(client):
    resp = client.post(BASE, json=FULL_PAYLOAD)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["phone_e164"] == "+966500000001"      # normalised to E.164
    assert body["email"] == "sara@example.com"
    assert body["stage"] == "NEW"
    assert body["consent_status"] == "GRANTED"
    assert body["score"] is not None and 0 <= body["score"] <= 100
    assert body["classification"] in {"HOT", "WARM", "COLD"}
    assert body["score_explanation"]["disclaimer"]
    assert body["contact_id"] is not None


def test_duplicate_submission_is_idempotent(client):
    first = client.post(BASE, json=FULL_PAYLOAD)
    second = client.post(BASE, json=FULL_PAYLOAD)
    assert first.status_code == 201
    assert second.status_code == 200                 # returned, not re-created
    assert first.json()["id"] == second.json()["id"]

    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Lead)).scalar_one() == 1
        # a duplicate_submission event is recorded on the timeline
        events = db.execute(
            select(LeadEvent.event_type).where(LeadEvent.lead_id == uuid.UUID(first.json()["id"]))
        ).scalars().all()
    assert "duplicate_submission" in events
    assert "created" in events
    assert "scored" in events


def test_same_person_via_different_source_creates_second_lead(client):
    client.post(BASE, json=FULL_PAYLOAD)
    payload = {**FULL_PAYLOAD, "source": "WHATSAPP_INBOUND"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Lead)).scalar_one() == 2


def test_anonymous_lead_never_deduplicates(client):
    anon = {"source": "LANDING_PAGE", "initial_inquiry": "hi", "utm_source": "tiktok"}
    a = client.post(BASE, json=anon)
    b = client.post(BASE, json=anon)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert a.json()["contact_id"] is None


def test_honeypot_is_silently_accepted(client):
    resp = client.post(BASE, json={**FULL_PAYLOAD, "website": "http://spam.example"})
    assert resp.status_code == 202
    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Lead)).scalar_one() == 0


def test_invalid_phone_is_rejected(client):
    resp = client.post(BASE, json={**FULL_PAYLOAD, "phone": "12"})
    assert resp.status_code == 422


def test_invalid_email_is_rejected(client):
    resp = client.post(BASE, json={**FULL_PAYLOAD, "email": "not-an-email"})
    assert resp.status_code == 422


def test_unknown_field_is_rejected(client):
    resp = client.post(BASE, json={**FULL_PAYLOAD, "is_admin": True})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Auth / authz
# --------------------------------------------------------------------------- #
def test_list_requires_authentication(client):
    assert client.get(BASE).status_code == 401
    assert client.get(BASE, headers={"X-API-Key": "wrong"}).status_code == 401


def test_list_with_admin_key_returns_items(client, admin_headers):
    client.post(BASE, json=FULL_PAYLOAD)
    resp = client.get(BASE, headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Sara"


def test_viewer_cannot_patch(client, admin_headers):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    resp = client.patch(f"{BASE}/{lead_id}", json={"name": "New"}, headers=_viewer_headers())
    assert resp.status_code == 403


def test_get_unknown_lead_is_404(client, admin_headers):
    resp = client.get(f"{BASE}/00000000-0000-0000-0000-000000000000", headers=admin_headers)
    assert resp.status_code == 404


def test_get_malformed_id_is_422(client, admin_headers):
    assert client.get(f"{BASE}/not-a-uuid", headers=admin_headers).status_code == 422


# --------------------------------------------------------------------------- #
# Pipeline transitions
# --------------------------------------------------------------------------- #
def test_illegal_stage_transition_is_409_for_staff(client, admin_headers):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    resp = client.patch(f"{BASE}/{lead_id}", json={"stage": "BOOKED"}, headers=_staff_headers())
    assert resp.status_code == 409


def test_legal_stage_transition_succeeds_for_staff(client, admin_headers):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    resp = client.patch(f"{BASE}/{lead_id}", json={"stage": "CONTACTED"}, headers=_staff_headers())
    assert resp.status_code == 200
    assert resp.json()["stage"] == "CONTACTED"


def test_owner_may_override_stage(client, admin_headers):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    resp = client.patch(f"{BASE}/{lead_id}", json={"stage": "COMPLETED"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["stage"] == "COMPLETED"


# --------------------------------------------------------------------------- #
# Re-scoring
# --------------------------------------------------------------------------- #
def test_patch_enriches_lead_and_rescores(client, admin_headers):
    # Start with a thin, anonymous lead -> low score.
    lead = client.post(BASE, json={"source": "LANDING_PAGE", "initial_inquiry": "hello"}).json()
    assert lead["classification"] == "COLD"

    resp = client.patch(
        f"{BASE}/{lead['id']}",
        json={
            "name": "Noura",
            "phone": "0555555555",
            "service_interest": "massage",
            "preferred_time_text": "Friday 8pm",
            "location_text": "Riyadh",
            "stage": "QUALIFIED",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["score"] > lead["score"]
    assert updated["classification"] in {"HOT", "WARM"}


def test_score_endpoint_returns_explanation(client, admin_headers):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    resp = client.post(f"{BASE}/{lead_id}/score", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["lead_id"] == lead_id
    assert 0 <= body["score"] <= 100
    assert body["classification"] in {"HOT", "WARM", "COLD"}
    assert body["explanation"]["factors"]
    assert isinstance(body["missing_info"], list)


def test_score_endpoint_requires_writer_role(client):
    lead_id = client.post(BASE, json=FULL_PAYLOAD).json()["id"]
    assert client.post(f"{BASE}/{lead_id}/score", headers=_viewer_headers()).status_code == 403

