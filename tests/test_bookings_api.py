"""Booking tests (Phase 5).

The most important property: a booking can never be CONFIRMED without explicit
human verification — neither through the API nor the service layer.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

BASE = "/api/leads"
BOOKINGS = "/api/bookings"


def _lead(client, **overrides) -> dict:
    payload = {
        "source": "WEBSITE_FORM",
        "name": "Sara",
        "phone": "0500000001",
        "service_interest": "home massage",
        "location_text": "Riyadh",
        "initial_inquiry": "I want to book an appointment",
        "consent_status": "GRANTED",
        **overrides,
    }
    resp = client.post(BASE, json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_create_booking_is_a_request_not_a_confirmation(client, admin_headers):
    lead = _lead(client)
    resp = client.post(
        BOOKINGS,
        json={"lead_id": lead["id"], "requested_time_at": "2030-01-01T18:00:00+00:00"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "REQUESTED"
    assert body["verified"] is False
    assert body["verified_by"] is None


def test_cannot_confirm_without_verification(client, admin_headers):
    lead = _lead(client)
    booking = client.post(
        BOOKINGS, json={"lead_id": lead["id"]}, headers=admin_headers
    ).json()
    resp = client.patch(
        f"{BOOKINGS}/{booking['id']}", json={"status": "CONFIRMED"}, headers=admin_headers
    )
    assert resp.status_code == 409
    assert "verifies" in resp.json()["detail"].lower()


def test_confirmation_with_verification_succeeds_and_advances_pipeline(client, admin_headers):
    lead = _lead(client)
    booking = client.post(
        BOOKINGS, json={"lead_id": lead["id"]}, headers=admin_headers
    ).json()

    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    resp = client.patch(
        f"{BOOKINGS}/{booking['id']}",
        json={
            "status": "CONFIRMED",
            "verified": True,
            "verified_by": "owner@massagevip.sa",
            "scheduled_at": when,
            "verification_notes": "Called the customer and checked the roster.",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CONFIRMED"
    assert body["verified"] is True
    assert body["verified_by"] == "owner@massagevip.sa"

    updated_lead = client.get(f"{BASE}/{lead['id']}", headers=admin_headers).json()
    assert updated_lead["stage"] == "BOOKED"
    assert updated_lead["booking_status"] == "CONFIRMED"


def test_completing_a_booking_moves_lead_to_completed(client, admin_headers):
    lead = _lead(client)
    booking = client.post(
        BOOKINGS, json={"lead_id": lead["id"]}, headers=admin_headers
    ).json()
    client.patch(
        f"{BOOKINGS}/{booking['id']}",
        json={"status": "CONFIRMED", "verified": True},
        headers=admin_headers,
    )
    resp = client.patch(
        f"{BOOKINGS}/{booking['id']}", json={"status": "COMPLETED"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "COMPLETED"

    updated = client.get(f"{BASE}/{lead['id']}", headers=admin_headers).json()
    assert updated["stage"] == "COMPLETED"


def test_booking_requires_authentication(client):
    assert client.post(BOOKINGS, json={}).status_code == 401


def test_booking_for_unknown_lead_is_404(client, admin_headers):
    resp = client.post(
        BOOKINGS,
        json={"lead_id": "00000000-0000-0000-0000-000000000000"},
        headers=admin_headers,
    )
    assert resp.status_code == 404
