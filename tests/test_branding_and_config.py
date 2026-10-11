"""Guards for brand configuration and production URL safety.

Both of these exist because the system can otherwise look healthy while being
wrong in a way the customer sees: drafts signed with the wrong brand, or
marketing links pointing at localhost.
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services import replies


# --------------------------------------------------------------------------- #
# Brand name is configurable, not hardcoded
# --------------------------------------------------------------------------- #
def test_draft_signature_uses_the_configured_brand(monkeypatch):
    monkeypatch.setattr(replies.settings, "business_name", "Massage Republic")
    body = replies.draft_reply(classification=None, missing_info=["the requested service"])
    assert "Massage Republic" in body
    assert "MassageVIP" not in body


def test_no_message_template_hardcodes_a_brand():
    """Every template must be brand-agnostic so a rebrand is a config change."""
    source = (replies.__file__)
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    # The literal may only appear as a default value in config, never in a template.
    assert "MassageVIP" not in text


def test_follow_up_templates_use_the_configured_brand(monkeypatch):
    monkeypatch.setattr(replies.settings, "business_name", "Massage Republic")
    for job_type in (
        "UNANSWERED_INQUIRY",
        "INCOMPLETE_BOOKING",
        "APPOINTMENT_REMINDER",
        "POST_APPOINTMENT_FEEDBACK",
        "REQUESTED_LATER",
    ):
        body = replies.followup_body(job_type, payload={"scheduled_at_text": "Tue 8pm"})
        assert "Massage Republic" in body, job_type


def test_every_draft_is_still_claim_free_after_rebranding(monkeypatch):
    monkeypatch.setattr(replies.settings, "business_name", "Massage Republic")
    body = replies.draft_reply(classification=None, missing_info=None).lower()
    assert "confirmed" not in body
    assert "sar" not in body


# --------------------------------------------------------------------------- #
# PUBLIC_BASE_URL must be real in production
# --------------------------------------------------------------------------- #
def _prod_settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "secret_key": "a" * 48,
        "admin_api_key": "b" * 48,
        "database_url": "postgresql://u:p@host:5432/db",
        "public_base_url": "https://massagerepublic.com",
    }
    return Settings(**{**base, **overrides})


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://0.0.0.0:8000",
        "https://your-domain.example",
    ],
)
def test_production_rejects_a_local_or_placeholder_public_base_url(bad_url):
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        _prod_settings(public_base_url=bad_url).assert_production_ready()


def test_production_accepts_a_real_public_base_url():
    _prod_settings().assert_production_ready()  # must not raise


def test_development_may_use_localhost():
    Settings(
        environment="development",
        public_base_url="http://127.0.0.1:8000",
    ).assert_production_ready()  # must not raise


def test_tracking_links_use_the_configured_base_url(monkeypatch):
    from app.services import marketing

    monkeypatch.setattr(marketing.settings, "public_base_url", "https://massagerepublic.com")
    url = marketing.tracking_url(channel="instagram", campaign_slug="launch")
    assert url.startswith("https://massagerepublic.com/?")
    assert "utm_source=instagram" in url
