"""CRM core entities: contacts (identity), campaigns, leads, lead events."""
from __future__ import annotations

import enum as _py_enum
import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.enums import (
    BookingStatus,
    ConsentStatus,
    LeadClassification,
    LeadSource,
    PipelineStage,
)

# JSON that is JSONB on PostgreSQL and TEXT-backed JSON elsewhere (SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _enum_col(py_enum: type[_py_enum.Enum], name: str) -> Enum:
    """Portable enum column: VARCHAR + CHECK everywhere (no PG native type)."""
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        length=40,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


def compute_dedupe_key(identity: str | None, source: str) -> str | None:
    """Stable dedupe key for a lead.

    Identity is the normalised strongest identifier we hold for the person
    (WhatsApp id, phone, or email). Returning ``None`` when identity is
    unknown means anonymous leads are *never* collapsed together.
    """
    if not identity:
        return None
    raw = f"{identity.strip().lower()}|{source.strip().upper()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Contact(UUIDMixin, TimestampMixin, Base):
    """One row per unique human. Other tables link here to avoid duplication."""

    __tablename__ = "contacts"

    wa_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)

    consent_status: Mapped[ConsentStatus] = mapped_column(
        _enum_col(ConsentStatus, "consent_status"), default=ConsentStatus.UNKNOWN, nullable=False
    )
    consent_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opt_out_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    leads: Mapped[list["Lead"]] = relationship(back_populates="contact")

    __table_args__ = (
        UniqueConstraint("wa_id", name="uq_contacts_wa_id"),
        UniqueConstraint("phone_e164", name="uq_contacts_phone_e164"),
        UniqueConstraint("email", name="uq_contacts_email"),
        Index("ix_contacts_identity_hash", "identity_hash"),
        CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 LIKE '+%'",
            name="phone_e164_e164_format",
        ),
    )


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source: Mapped[LeadSource] = mapped_column(
        _enum_col(LeadSource, "lead_source"), default=LeadSource.OTHER, nullable=False
    )
    utm_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(160), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(160), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(160), nullable=True)
    landing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    spend_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    leads: Mapped[list["Lead"]] = relationship(back_populates="campaign")

    __table_args__ = (
        UniqueConstraint("utm_campaign", "channel", name="uq_campaigns_utm_channel"),
    )


class Lead(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )

    source: Mapped[LeadSource] = mapped_column(
        _enum_col(LeadSource, "lead_source"), default=LeadSource.OTHER, nullable=False
    )
    source_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Voluntarily provided identification (may be absent for anonymous leads).
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    wa_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    initial_inquiry: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preferred_time_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preferred_time_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_text: Mapped[str | None] = mapped_column(String(200), nullable=True)

    stage: Mapped[PipelineStage] = mapped_column(
        _enum_col(PipelineStage, "pipeline_stage"), default=PipelineStage.NEW, nullable=False
    )
    booking_status: Mapped[BookingStatus | None] = mapped_column(
        _enum_col(BookingStatus, "booking_status"), nullable=True
    )
    consent_status: Mapped[ConsentStatus] = mapped_column(
        _enum_col(ConsentStatus, "consent_status"), default=ConsentStatus.UNKNOWN, nullable=False
    )

    # Scoring (populated by the qualification engine).
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification: Mapped[LeadClassification | None] = mapped_column(
        _enum_col(LeadClassification, "lead_classification"), nullable=True
    )
    score_explanation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    missing_info: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Attribution (denormalised for direct-form leads with no Campaign row yet).
    utm_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(160), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(160), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(160), nullable=True)

    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped[Contact | None] = relationship(back_populates="leads")
    campaign: Mapped[Campaign | None] = relationship(back_populates="leads")
    events: Mapped[list["LeadEvent"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_leads_dedupe_key"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        Index("ix_leads_stage", "stage"),
        Index("ix_leads_classification", "classification"),
        Index("ix_leads_created_at", "created_at"),
        Index("ix_leads_source", "source"),
        Index("ix_leads_campaign_id", "campaign_id"),
        Index("ix_leads_phone_e164", "phone_e164"),
    )


class LeadEvent(UUIDMixin, Base):
    """Append-only timeline of everything that happens to a lead."""

    __tablename__ = "lead_events"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor: Mapped[str] = mapped_column(String(120), default="system", nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead: Mapped[Lead] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_lead_events_lead_id_created_at", "lead_id", "created_at"),
        Index("ix_lead_events_event_type", "event_type"),
    )
