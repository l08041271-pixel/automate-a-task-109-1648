"""Analytics summary tests (Phase 6/7)."""
from __future__ import annotations

BASE = "/api/analytics/summary"
LEADS = "/api/leads"


def _lead(client, **overrides):
    payload = {
        "source": "WEBSITE_FORM",
        "name": "Sara",
        "phone": "0500000001",
        "service_interest": "home massage",
        "location_text": "Riyadh",
        "initial_inquiry": "I want to book an appointment tonight",
        "consent_status": "GRANTED",
        **overrides,
    }
    return client.post(LEADS, json=payload)


def test_summary_requires_authentication(client):
    assert client.get(BASE).status_code == 401


def test_empty_summary_has_zeroed_measured_metrics(client, admin_headers):
    body = client.get(BASE, headers=admin_headers).json()
    assert body["leads"]["total"] == 0
    assert body["bookings"]["confirmed"] == 0
    assert body["conversion"]["lead_to_booking_rate_pct"] == 0.0
    assert body["money"]["provenance"] == "not_recorded"
    assert body["system_health"]["database"] == "ok"


def test_summary_every_metric_carries_provenance(client, admin_headers):
    body = client.get(BASE, headers=admin_headers).json()
    assert body["leads"]["provenance"] == "measured"
    assert body["whatsapp"]["provenance"] == "measured"
    assert body["bookings"]["provenance"] == "measured"
    assert body["conversion"]["provenance"] == "measured"
    assert body["follow_ups"]["provenance"] == "measured"
    assert "measured" in body["measurement_notes"]


def test_summary_counts_leads_and_derives_conversion(client, admin_headers):
    for i in range(3):
        _lead(client, phone=f"050000000{i + 1}")

    body = client.get(BASE, headers=admin_headers).json()
    assert body["leads"]["total"] == 3
    assert body["leads"]["new_today"] == 3
    assert body["leads"]["by_source"]["WEBSITE_FORM"] == 3
    assert body["leads"]["by_classification"]

    # Confirm one booking -> conversion becomes 1/3 = 33.3%
    lead_id = client.get(LEADS, headers=admin_headers).json()["items"][0]["id"]
    booking = client.post(
        "/api/bookings", json={"lead_id": lead_id}, headers=admin_headers
    ).json()
    client.patch(
        f"/api/bookings/{booking['id']}",
        json={"status": "CONFIRMED", "verified": True},
        headers=admin_headers,
    )

    body = client.get(BASE, headers=admin_headers).json()
    assert body["bookings"]["confirmed"] == 1
    assert body["conversion"]["lead_to_booking_rate_pct"] == 33.3


def test_summary_reports_recorded_revenue_when_prices_exist(client, admin_headers):
    lead_id = _lead(client).json()["id"]
    booking = client.post(
        "/api/bookings",
        json={"lead_id": lead_id, "price_amount": 300.0},
        headers=admin_headers,
    ).json()
    client.patch(
        f"/api/bookings/{booking['id']}",
        json={"status": "CONFIRMED", "verified": True, "price_amount": 300.0},
        headers=admin_headers,
    )

    body = client.get(BASE, headers=admin_headers).json()
    assert body["money"]["revenue_recorded"] == 300.0
    assert body["money"]["priced_bookings"] == 1
    assert body["money"]["provenance"] == "recorded"
    assert "NOT a full P&L" in body["money"]["caveat"]


def test_summary_window_is_configurable(client, admin_headers):
    body = client.get(f"{BASE}?days=7", headers=admin_headers).json()
    assert body["period_days"] == 7
    assert client.get(f"{BASE}?days=0", headers=admin_headers).status_code == 422
