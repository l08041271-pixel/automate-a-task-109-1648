"""AI Growth Agent tests (Phase 8).

The agent must stay in recommendation-only mode: it reports problems, it never
acts. These tests assert that, plus the honesty of every recommendation.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.enums import UserRole
from app.db.models import AuditLog, AutomationRun
from app.db.session import SessionLocal
from app.services import growth_agent, marketing

LEADS = "/api/leads"
GROWTH = "/api/growth"


def _owner_headers() -> dict[str, str]:
    token = create_access_token("owner@massagevip.sa", UserRole.OWNER)
    return {"Authorization": f"Bearer {token}"}


def _viewer_headers() -> dict[str, str]:
    token = create_access_token("viewer@massagevip.sa", UserRole.VIEWER)
    return {"Authorization": f"Bearer {token}"}


def _cold_lead(client, i: int):
    return client.post(
        LEADS,
        json={
            "source": "LANDING_PAGE",
            "initial_inquiry": "hello",
            "email": f"anon{i}@example.com",
        },
    )


# --------------------------------------------------------------------------- #
# Core behaviour
# --------------------------------------------------------------------------- #
def test_empty_database_yields_the_capture_recommendation(client):
    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=7)
        db.commit()

    assert report.mode == "recommendation_only"
    assert report.metrics["leads"]["total"] == 0
    titles = [r.title for r in report.recommendations]
    assert any("No leads have been captured" in t for t in titles)

    with SessionLocal() as db:
        runs = db.execute(select(AutomationRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].run_type == "growth_analysis"
    assert runs[0].metrics["leads_total"] == 0


def test_report_states_it_is_recommendation_only(client):
    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=7)
        db.commit()
    payload = report.as_dict()
    assert payload["mode"] == "recommendation_only"
    assert "Recommendation-only mode" in payload["disclaimer"]
    assert "does not 'learn'" in payload["disclaimer"]


def test_cold_dominant_pipeline_is_flagged(client):
    for i in range(5):
        assert _cold_lead(client, i).status_code == 201

    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=7)
        db.commit()

    categories = {r.category for r in report.recommendations}
    assert "qualification" in categories
    rec = next(r for r in report.recommendations if r.category == "qualification")
    # Every recommendation must cite real numbers.
    assert rec.evidence["cold_leads"] == 5
    assert rec.evidence["total_leads"] == 5


def test_escalated_whatsapp_conversation_is_flagged(client):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "PN"},
            "contacts": [{"profile": {"name": "Sara"}, "wa_id": "966500000333"}],
            "messages": [{"from": "966500000333", "id": "wamid.X", "timestamp": "1700000000",
                          "type": "text",
                          "text": {"body": "I want to book a home massage in Riyadh tonight"}}],
        }}]}],
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    assert client.post(
        "/api/webhooks/whatsapp", content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    ).status_code == 200

    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=7)
        db.commit()

    assert any(r.category == "operations" and "WhatsApp" in r.title
               for r in report.recommendations)


def test_analysis_never_requires_authorization_for_read_only_findings(client):
    for i in range(5):
        _cold_lead(client, i)
    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=7)
        db.commit()
    # The cold-pipeline finding is advice, not a consequential action.
    rec = next(r for r in report.recommendations if r.category == "qualification")
    assert rec.requires_authorization is False


# --------------------------------------------------------------------------- #
# Marketing drafts
# --------------------------------------------------------------------------- #
def test_marketing_drafts_cover_every_required_channel():
    drafts = marketing.build_drafts(campaign_name="Riyadh Launch")
    channels = {d.channel for d in drafts}
    assert channels == {"instagram", "tiktok", "whatsapp_status", "landing_page", "ad_campaign"}


def test_every_draft_has_a_tracking_link_and_needs_authorization():
    for draft in marketing.build_drafts(campaign_name="Riyadh Launch"):
        assert "utm_source=" in draft.tracking_url
        assert "utm_medium=" in draft.tracking_url
        assert "utm_campaign=riyadh-launch" in draft.tracking_url
        assert draft.call_to_action
        assert draft.requires_publishing_authorization is True


def test_drafts_contain_no_unverifiable_claims_or_prices():
    for draft in marketing.build_drafts():
        text = f"{draft.headline} {draft.body} {draft.call_to_action}".lower()
        for forbidden in ("best in", "guaranteed", "#1", "rated 5", "testimonial", "sar"):
            assert forbidden not in text


def test_draft_guard_rejects_an_unverifiable_claim():
    import pytest

    from app.services.marketing import MarketingDraft, _assert_no_unverifiable_claims

    bad = MarketingDraft(
        channel="instagram", headline="Best in Riyadh", body="guaranteed results",
        call_to_action="book", tracking_url="http://x",
    )
    with pytest.raises(ValueError):
        _assert_no_unverifiable_claims(bad)


def test_marketing_endpoint_never_publishes(client):
    resp = client.get(f"{GROWTH}/marketing-drafts", headers=_viewer_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is False
    assert len(body["drafts"]) == 5
    assert "Publishing requires" in body["note"]


# --------------------------------------------------------------------------- #
# API + authorisation
# --------------------------------------------------------------------------- #
def test_growth_run_requires_authentication_and_owner(client):
    assert client.post(f"{GROWTH}/run").status_code == 401
    assert client.post(f"{GROWTH}/run", headers=_viewer_headers()).status_code == 403


def test_growth_run_returns_recommendations_and_is_audited(client):
    resp = client.post(f"{GROWTH}/run?days=7", headers=_owner_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "recommendation_only"
    assert body["run_id"]
    assert isinstance(body["recommendations"], list)
    assert body["summary_text"]

    with SessionLocal() as db:
        actions = db.execute(select(AuditLog.action)).scalars().all()
    assert "growth_analysis_run" in actions


def test_reports_endpoint_lists_previous_runs(client):
    client.post(f"{GROWTH}/run?days=7", headers=_owner_headers())
    resp = client.get(f"{GROWTH}/reports", headers=_owner_headers())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["run_type"] == "growth_analysis"


def test_authorization_records_audit_but_does_not_act(client):
    resp = client.post(
        f"{GROWTH}/authorizations",
        json={
            "recommendation_id": "abc123",
            "action_type": "campaign_budget_change",
            "approved": True,
            "note": "Approved a 200 SAR test budget.",
        },
        headers=_owner_headers(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recorded"] is True
    assert "did not perform the action" in body["message"]

    with SessionLocal() as db:
        entry = db.execute(
            select(AuditLog).where(AuditLog.action == "growth_action_authorized")
        ).scalars().one()
    assert entry.after_data["action_type"] == "campaign_budget_change"
    assert entry.actor == "owner@massagevip.sa"


def test_authorization_requires_owner(client):
    resp = client.post(
        f"{GROWTH}/authorizations",
        json={"recommendation_id": "abc123", "action_type": "publish", "approved": True},
        headers=_viewer_headers(),
    )
    assert resp.status_code == 403
