"""Reply templates for the WhatsApp sales assistant.

Design rules (do not break these):
  * Never state or imply a price.
  * Never state that a slot is available or that a booking is confirmed.
  * Never invent reviews, ratings, staff names or opening hours.
  * Always make clear that a human verifies availability before confirmation.
  * Keep messages short and professional (WhatsApp is a chat medium).
"""
from __future__ import annotations

from app.db.enums import LeadClassification

_SIGNATURE = "— MassageVIP Riyadh"

ASK_FOR_INFO = (
    "Thank you for contacting MassageVIP Riyadh. 🙏\n\n"
    "To check availability for you, could you share:\n"
    "{missing}\n\n"
    "As soon as we have this, our team will verify availability and confirm your "
    "appointment with you."
)

RECEIVED_FULL = (
    "Thank you for contacting MassageVIP Riyadh. 🙏\n\n"
    "We have received your request. Our team will verify availability for your "
    "preferred time and confirm with you shortly."
)

NEEDS_HUMAN = (
    "Thank you for contacting MassageVIP Riyadh. 🙏\n\n"
    "Your request needs a quick check by our team. Someone will reply here shortly "
    "to confirm the details with you."
)

OPT_OUT_CONFIRMATION = (
    "You have been unsubscribed and will not receive further messages from us. "
    "Reply START at any time to opt back in."
)


def draft_reply(
    *,
    classification: LeadClassification | None,
    missing_info: list[str] | None,
    opted_out: bool = False,
    needs_human: bool = False,
) -> str | None:
    """Return a draft reply, or ``None`` when we must stay silent."""
    if opted_out:
        return None  # we never message someone who opted out
    if needs_human:
        return f"{NEEDS_HUMAN}\n\n{_SIGNATURE}"
    missing = [m for m in (missing_info or []) if m]
    if missing:
        bullet_list = "\n".join(f"• {item}" for item in missing[:3])
        return f"{ASK_FOR_INFO.format(missing=bullet_list)}\n\n{_SIGNATURE}"
    return f"{RECEIVED_FULL}\n\n{_SIGNATURE}"
