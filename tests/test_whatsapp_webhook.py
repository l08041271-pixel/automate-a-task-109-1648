"""WhatsApp webhook tests (Phase 4).

Covers the verification handshake, HMAC signature enforcement, message
ingestion, opt-out handling, HOT escalation and the guarantee that nothing is
ever auto-sent.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import select

from app.db.enums import ConsentStatus, ConversationStatus, MessageStatus
from app.db.models import Contact, Conversation, Lead, Message
from app.db.session import SessionLocal
from app.services import whatsapp as wa

URL = "/api/webhooks/whatsapp"
APP_SECRET = "test-app-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _payload(text: str, wa_id: str = "966500000111", msg_id: str | None = None,
             name: str = "Test User") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "966500000000",
                                         "phone_number_id": "PNID"},
                            "contacts": [{"profile": {"name": name}, "wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": msg_id or f"wamid.{uuid.uuid4().hex}",
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _post(client, payload: dict, *, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    headers["X-Hub-Signature-256"] = signature if signature is not None else _sign(body)
    return client.post(URL, content=body, headers=headers)


# --------------------------------------------------------------------------- #
# Handshake
# --------------------------------------------------------------------------- #
def test_verification_handshake_returns_challenge(client):
    resp = client.get(
        URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token",
                "hub.challenge": "12345"},
    )
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_verification_with_wrong_token_is_403(client):
    resp = client.get(
        URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Signature enforcement
# --------------------------------------------------------------------------- #
def test_missing_signature_is_rejected(client):
    body = json.dumps(_payload("hi")).encode()
    resp = client.post(URL, content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 401


def test_tampered_signature_is_rejected(client):
    resp = _post(client, _payload("hi"), signature="sha256=" + "0" * 64)
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def test_valid_message_creates_contact_conversation_lead_and_draft(client):
    resp = _post(client, _payload("Hello, I would like to book a home massage in Riyadh tonight"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["processed"] == 1

    with SessionLocal() as db:
        contact = db.execute(select(Contact)).scalars().one()
        assert contact.wa_id == "966500000111"
        assert contact.phone_e164 == "+966500000111"

        lead = db.execute(select(Lead)).scalars().one()
        assert lead.source.value == "WHATSAPP_INBOUND"
        assert lead.initial_inquiry.startswith("Hello")
        assert lead.score is not None

        convo = db.execute(select(Conversation)).scalars().one()
        assert convo.message_count == 1

        messages = db.execute(select(Message).order_by(Message.created_at)).scalars().all()
        assert len(messages) == 2  # inbound + drafted reply
        assert messages[0].status == MessageStatus.RECEIVED
        assert messages[1].status == MessageStatus.DRAFTED
        assert messages[1].is_automated is True


def test_duplicate_webhook_delivery_is_idempotent(client):
    payload = _payload("hello there", msg_id="wamid.DUPLICATE")
    first = _post(client, payload)
    second = _post(client, payload)
    assert first.json()["processed"] == 1
    assert second.json()["duplicates"] == 1

    with SessionLocal() as db:
        assert len(db.execute(select(Lead)).scalars().all()) == 1
        assert len(db.execute(select(Message)).scalars().all()) == 2  # no double-store


def test_reply_is_drafted_but_never_sent(client):
    _post(client, _payload("hi"))
    with SessionLocal() as db:
        statuses = db.execute(select(Message.status)).scalars().all()
    assert MessageStatus.SENT not in statuses
    assert MessageStatus.DRAFTED in statuses


def test_draft_never_promises_availability_price_or_confirmation(client):
    _post(client, _payload("Can you confirm a booking for tonight? How much is it?"))
    with SessionLocal() as db:
        drafts = db.execute(
            select(Message.body).where(Message.status == MessageStatus.DRAFTED)
        ).scalars().all()
    assert drafts
    for text in drafts:
        lowered = text.lower()
        assert "confirmed" not in lowered
        assert "sar" not in lowered
        assert "price" not in lowered
        assert "verify availability" in lowered or "unsubscribed" in lowered


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #
def test_stop_keyword_marks_contact_opted_out_and_closes_conversation(client):
    _post(client, _payload("STOP"))
    with SessionLocal() as db:
        contact = db.execute(select(Contact)).scalars().one()
        assert contact.consent_status == ConsentStatus.OPTED_OUT
        assert contact.opted_out_at is not None
        convo = db.execute(select(Conversation)).scalars().one()
        assert convo.status == ConversationStatus.CLOSED


def test_start_keyword_re_opts_in(client):
    _post(client, _payload("stop"))
    _post(client, _payload("start", msg_id="wamid.OPTIN"))
    with SessionLocal() as db:
        contact = db.execute(select(Contact)).scalars().one()
        assert contact.consent_status == ConsentStatus.GRANTED


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #
def test_hot_lead_is_escalated_to_owner(client):
    _post(client, _payload("I want to book a home massage in Riyadh tonight, my name is Sara"))
    with SessionLocal() as db:
        convo = db.execute(select(Conversation)).scalars().one()
        lead = db.execute(select(Lead)).scalars().one()
    assert lead.classification.value == "HOT"
    assert convo.status == ConversationStatus.ESCALATED
    assert convo.assigned_to == "owner"


# --------------------------------------------------------------------------- #
# Sending is disabled by default
# --------------------------------------------------------------------------- #
def test_send_text_refuses_while_dry_run_enabled():
    with pytest.raises(wa.WhatsAppNotConfigured):
        wa.send_text("966500000111", "hello")


def test_parse_webhook_ignores_non_message_events():
    messages, statuses = wa.parse_webhook({"object": "page", "entry": []})
    assert messages == [] and statuses == []


def test_opt_out_and_opt_in_keywords():
    assert wa.is_opt_out("STOP") is True
    assert wa.is_opt_out("\u0625\u0644\u063a\u0627\u0621") is True
    assert wa.is_opt_out("hello") is False
    assert wa.is_opt_in("start") is True
