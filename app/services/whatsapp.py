"""WhatsApp Business Platform helpers: parsing, signature verification, sending.

Scope and safety rules baked in here:
  * Only the official Cloud API webhook shape is accepted.
  * Inbound POSTs are rejected unless the ``X-Hub-Signature-256`` HMAC matches.
  * Outbound sending is DISABLED unless explicitly configured (dry-run default),
    so nothing can be messaged to a customer by accident.
  * Nothing in this module invents availability, prices or confirmations.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.core.logging import get_logger, log_extra

logger = get_logger(__name__)

# Opt-out / opt-in keywords (English + Arabic), matched case-insensitively.
OPT_OUT_KEYWORDS = {
    "stop", "unsubscribe", "cancel", "opt out", "optout", "remove me",
    "إلغاء", "الغاء", "توقف", "لا تراسلني", "اوقف",
}
OPT_IN_KEYWORDS = {"start", "subscribe", "اشتراك", "ابدأ"}


@dataclass
class InboundMessage:
    wa_id: str
    message_id: str
    msg_type: str
    text: str | None
    profile_name: str | None
    phone_number_id: str | None
    timestamp: datetime
    raw: dict


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Validate Meta's ``X-Hub-Signature-256`` over the raw request body.

    Fails closed when no app secret is configured.
    """
    secret = settings.whatsapp_app_secret
    if not secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, provided)


def _ts_to_dt(value: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def parse_webhook(payload: dict) -> tuple[list[InboundMessage], list[dict]]:
    """Extract inbound messages and delivery statuses from a webhook payload."""
    messages: list[InboundMessage] = []
    statuses: list[dict] = []

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            if change.get("field") != "messages":
                continue
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            contacts = {c.get("wa_id"): c for c in (value.get("contacts") or [])}

            for status in value.get("statuses", []) or []:
                statuses.append(status)

            for msg in value.get("messages", []) or []:
                wa_id = msg.get("from")
                if not wa_id:
                    continue
                msg_type = msg.get("type", "unknown")
                text = None
                if msg_type == "text":
                    text = ((msg.get("text") or {}).get("body") or "").strip()
                elif msg_type == "button":
                    text = ((msg.get("button") or {}).get("text") or "").strip()
                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    text = (
                        ((interactive.get("button_reply") or {}).get("title"))
                        or ((interactive.get("list_reply") or {}).get("title"))
                        or ""
                    ).strip()

                profile = (contacts.get(wa_id) or {}).get("profile") or {}
                messages.append(
                    InboundMessage(
                        wa_id=str(wa_id),
                        message_id=str(msg.get("id") or ""),
                        msg_type=msg_type,
                        text=text,
                        profile_name=profile.get("name"),
                        phone_number_id=phone_number_id,
                        timestamp=_ts_to_dt(msg.get("timestamp")),
                        raw=msg,
                    )
                )
    return messages, statuses


def is_opt_out(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().lower() in OPT_OUT_KEYWORDS


def is_opt_in(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().lower() in OPT_IN_KEYWORDS


class WhatsAppNotConfigured(Exception):
    pass


def send_text(to_wa_id: str, body: str) -> dict:
    """Send a text message through the Cloud API.

    Raises :class:`WhatsAppNotConfigured` unless a token + phone number id are
    present AND dry-run is off. This guarantees the default configuration can
    never message a real customer.
    """
    if settings.whatsapp_dry_run:
        raise WhatsAppNotConfigured("WHATSAPP_DRY_RUN is enabled; not sending")
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppNotConfigured("WhatsApp access token / phone number id missing")

    url = (
        f"{settings.whatsapp_graph_base}/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_wa_id,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    logger.info("whatsapp.sent", extra=log_extra(to=to_wa_id, status=resp.status_code))
    return resp.json()
