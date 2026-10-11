"""Draft marketing content for review.

Rules enforced by construction:
  * Output is DRAFTS ONLY. Nothing here publishes anything. Publishing requires
    the relevant account to be connected, permissions granted and an explicit
    approval — see ``requires_publishing_authorization`` on every draft.
  * No invented testimonials, reviews, ratings, statistics or guarantees.
  * No prices (they must come from the business, not a template).
  * Every draft carries a UTM-tagged tracking link so performance is measurable.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from app.core.config import settings

#: Phrases that would imply an unverifiable claim. Drafts are checked against
#: these before being returned, so a template edit cannot sneak a claim in.
_FORBIDDEN_CLAIMS = (
    "best in", "#1", "number one", "guaranteed", "miracle", "cure",
    "100% satisfaction", "rated 5", "testimonial", "customers say",
)


@dataclass
class MarketingDraft:
    channel: str
    headline: str
    body: str
    call_to_action: str
    tracking_url: str
    requires_publishing_authorization: bool = True
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def tracking_url(*, channel: str, campaign_slug: str, medium: str = "social") -> str:
    """Build a UTM-tagged link so clicks can be attributed to a campaign."""
    query = urlencode(
        {
            "utm_source": channel,
            "utm_medium": medium,
            "utm_campaign": campaign_slug,
        }
    )
    return f"{settings.public_base_url.rstrip('/')}/?{query}"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "general"


def build_drafts(*, campaign_name: str = "always-on", city: str | None = None) -> list[MarketingDraft]:
    """Return one draft per channel for review. Nothing is published."""
    city = city or settings.business_city
    slug = _slug(campaign_name)

    drafts = [
        MarketingDraft(
            channel="instagram",
            headline=f"Book a massage at home in {city}",
            body=(
                f"Professional massage, booked around your schedule in {city}.\n\n"
                "Send us a message with your preferred day and time and our team will "
                "confirm availability with you."
            ),
            call_to_action="Message us to check availability",
            tracking_url=tracking_url(channel="instagram", campaign_slug=slug),
            notes="Attach original photography. Do not add reviews or ratings.",
        ),
        MarketingDraft(
            channel="tiktok",
            headline="60-second booking walkthrough",
            body=(
                "Show, in 3 quick shots, how easy it is to request a booking: open the "
                "chat, send your preferred time, receive confirmation once our team "
                "verifies availability."
            ),
            call_to_action="Tap the link to request a time",
            tracking_url=tracking_url(channel="tiktok", campaign_slug=slug),
            notes="Use only footage you own. No on-screen claims about results.",
        ),
        MarketingDraft(
            channel="whatsapp_status",
            headline="Now taking booking requests",
            body=(
                f"Serving {city}. Reply to this chat with your preferred day and time "
                "and our team will check availability for you."
            ),
            call_to_action="Reply here to request a time",
            tracking_url=tracking_url(channel="whatsapp_status", campaign_slug=slug, medium="referral"),
            notes=(
                "Posting to WhatsApp Status requires a connected business account and "
                "must respect contact consent and platform rules."
            ),
        ),
        MarketingDraft(
            channel="landing_page",
            headline=f"Massage booking requests in {city}",
            body=(
                "A single-purpose page: explain the service in two sentences, show the "
                "booking form above the fold, and keep a WhatsApp button pinned."
            ),
            call_to_action="Request your preferred time",
            tracking_url=tracking_url(channel="landing_page", campaign_slug=slug, medium="website"),
            notes="Wire the form to POST /api/leads and keep the honeypot field enabled.",
        ),
        MarketingDraft(
            channel="ad_campaign",
            headline="Paid test — 3 ad variants",
            body=(
                "Variant A: home service emphasis. Variant B: same-day availability "
                "emphasis. Variant C: convenience emphasis. Run a small budget test and "
                "compare cost per qualified lead."
            ),
            call_to_action="Request a time",
            tracking_url=tracking_url(channel="ad_campaign", campaign_slug=slug, medium="cpc"),
            notes=(
                "Requires explicit budget authorisation before any spend. Do not launch "
                "until the account and payment method are configured and approved."
            ),
        ),
    ]

    for draft in drafts:
        _assert_no_unverifiable_claims(draft)
    return drafts


def _assert_no_unverifiable_claims(draft: MarketingDraft) -> None:
    haystack = f"{draft.headline} {draft.body} {draft.call_to_action}".lower()
    for phrase in _FORBIDDEN_CLAIMS:
        if phrase in haystack:
            raise ValueError(
                f"draft for {draft.channel} contains an unverifiable claim: '{phrase}'"
            )
