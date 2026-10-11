"""Ingest inbound WhatsApp messages into the CRM.

Creates/updates: contact -> conversation -> message -> lead -> drafted reply.
Nothing is ever *sent* from here; replies are stored with status DRAFTED and
only leave the building when an operator or an explicitly-enabled sender does it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_extra
from app.core.phone import PhoneError, normalize_phone
from app.db.enums import (
    ConsentStatus,
    ConversationStatus,
    LeadClassification,
    LeadSource,
    MessageDirection,
    MessageStatus,
)
from app.db.models import Contact, Conversation, Lead, Message
from app.schemas.lead import LeadCreate
from app.services import extraction
from app.services import leads as leads_service
from app.services import replies as replies_service
from app.services import whatsapp as wa
from app.services.whatsapp import InboundMessage

logger = get_logger(__name__)


@dataclass
class IngestResult:
    contact: Contact
    conversation: Conversation
    message: Message
    lead: Lead | None
    is_new_lead: bool
    opted_out: bool
    escalated: bool
    draft_reply: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def get_or_create_conversation(
    db: Session, contact: Contact, *, wa_conversation_id: str
) -> Conversation:
    conversation = db.execute(
        select(Conversation).where(
            Conversation.channel == "whatsapp",
            Conversation.wa_conversation_id == wa_conversation_id,
        )
    ).scalars().first()
    if conversation is None:
        conversation = Conversation(
            contact_id=contact.id,
            channel="whatsapp",
            wa_conversation_id=wa_conversation_id,
            status=ConversationStatus.OPEN,
        )
        db.add(conversation)
        db.flush()
    return conversation


def _find_whatsapp_lead(db: Session, contact_id) -> Lead | None:
    return db.execute(
        select(Lead)
        .where(Lead.contact_id == contact_id, Lead.source == LeadSource.WHATSAPP_INBOUND)
        .order_by(Lead.created_at.desc())
    ).scalars().first()


def ingest_inbound(db: Session, msg: InboundMessage) -> IngestResult | None:
    """Store an inbound message. Returns ``None`` for a duplicate delivery."""
    if msg.message_id:
        existing = db.execute(
            select(Message).where(Message.wa_message_id == msg.message_id)
        ).scalars().first()
        if existing is not None:
            logger.info("whatsapp.duplicate_webhook", extra=log_extra(message_id=msg.message_id))
            return None

    try:
        phone = normalize_phone(msg.wa_id)
    except PhoneError:
        phone = None

    contact = leads_service.resolve_or_create_contact(
        db, wa_id=msg.wa_id, phone_e164=phone, name=msg.profile_name
    )
    assert contact is not None  # wa_id is always present

    # --- Consent handling --------------------------------------------------
    opted_out = wa.is_opt_out(msg.text)
    if opted_out:
        contact.consent_status = ConsentStatus.OPTED_OUT
        contact.opted_out_at = _now()
        contact.opt_out_reason = "whatsapp_stop_keyword"
    elif wa.is_opt_in(msg.text):
        contact.consent_status = ConsentStatus.GRANTED
        contact.consent_source = "whatsapp_opt_in"
        contact.opted_out_at = None

    conversation = get_or_create_conversation(db, contact, wa_conversation_id=msg.wa_id)

    message = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        wa_message_id=msg.message_id or None,
        msg_type=msg.msg_type,
        body=msg.text,
        status=MessageStatus.RECEIVED,
        is_automated=False,
        raw_payload=msg.raw,
    )
    db.add(message)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None

    conversation.last_message_at = msg.timestamp
    conversation.message_count = (conversation.message_count or 0) + 1
    contact.last_seen_at = _now()

    # --- Lead --------------------------------------------------------------
    signals = extraction.extract_signals(msg.text)
    lead = _find_whatsapp_lead(db, contact.id)
    is_new_lead = False
    if lead is None:
        payload = LeadCreate(
            source=LeadSource.WHATSAPP_INBOUND,
            source_detail="whatsapp_cloud_api",
            name=msg.profile_name,
            phone=msg.wa_id,
            wa_id=msg.wa_id,
            initial_inquiry=msg.text,
            service_interest=signals.service_interest,
            location_text=signals.location_text,
            preferred_time_text=signals.preferred_time_text,
            consent_status=contact.consent_status,
        )
        lead, is_new_lead = leads_service.create_lead(db, payload, actor="whatsapp")
    else:
        if not lead.initial_inquiry and msg.text:
            lead.initial_inquiry = msg.text
        # Only ever FILL blanks; never overwrite what a human confirmed.
        if signals.service_interest and not lead.service_interest:
            lead.service_interest = signals.service_interest
        if signals.location_text and not lead.location_text:
            lead.location_text = signals.location_text
        if signals.preferred_time_text and not lead.preferred_time_text:
            lead.preferred_time_text = signals.preferred_time_text
        lead.last_activity_at = _now()
        if lead.consent_status != contact.consent_status:
            lead.consent_status = contact.consent_status
        leads_service.apply_score(db, lead, actor="whatsapp")

    if signals.evidence:
        leads_service.record_event(
            db, lead.id, "signals_extracted", actor="whatsapp",
            metadata={"evidence": signals.evidence, "basis": "customer_message_text"},
        )

    conversation.lead_id = lead.id

    # --- Escalation --------------------------------------------------------
    escalated = lead.classification == LeadClassification.HOT
    if escalated and conversation.status == ConversationStatus.OPEN:
        conversation.status = ConversationStatus.ESCALATED
        conversation.assigned_to = "owner"
        leads_service.record_event(
            db, lead.id, "escalated_to_owner", to_value="owner", actor="whatsapp",
            metadata={"reason": "HOT classification"},
        )

    if opted_out:
        conversation.status = ConversationStatus.CLOSED
        leads_service.record_event(
            db, lead.id, "opted_out", actor="whatsapp",
            metadata={"channel": "whatsapp", "reason": "stop keyword"},
        )

    # --- Draft (never sent from here) --------------------------------------
    draft_text = _build_draft(lead, opted_out)
    if draft_text:
        db.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.OUTBOUND,
                msg_type="text",
                body=draft_text,
                status=MessageStatus.DRAFTED,
                is_automated=True,
            )
        )
        leads_service.record_event(
            db, lead.id, "reply_drafted", actor="whatsapp",
            metadata={"automated": True, "sent": False},
        )

    db.flush()
    logger.info(
        "whatsapp.ingested",
        extra=log_extra(
            wa_id=msg.wa_id, is_new_lead=is_new_lead,
            classification=lead.classification.value if lead.classification else None,
            escalated=escalated, opted_out=opted_out,
        ),
    )
    return IngestResult(
        contact=contact,
        conversation=conversation,
        message=message,
        lead=lead,
        is_new_lead=is_new_lead,
        opted_out=opted_out,
        escalated=escalated,
        draft_reply=draft_text,
    )


def _build_draft(lead: Lead, opted_out: bool) -> str | None:
    if opted_out:
        # A single transactional confirmation of the opt-out is appropriate.
        return replies_service.OPT_OUT_CONFIRMATION
    return replies_service.draft_reply(
        classification=lead.classification,
        missing_info=lead.missing_info,
    )

