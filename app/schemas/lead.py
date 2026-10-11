"""Lead request/response schemas with strict validation."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.phone import PhoneError, normalize_phone
from app.db.enums import (
    BookingStatus,
    ConsentStatus,
    LeadClassification,
    LeadSource,
    PipelineStage,
)


class _UTMMixin(BaseModel):
    utm_source: str | None = Field(None, max_length=120)
    utm_medium: str | None = Field(None, max_length=120)
    utm_campaign: str | None = Field(None, max_length=160)
    utm_content: str | None = Field(None, max_length=160)
    utm_term: str | None = Field(None, max_length=160)


class LeadCreate(_UTMMixin):
    """Payload for POST /api/leads (public form + server-to-server)."""

    model_config = ConfigDict(extra="forbid")

    source: LeadSource = LeadSource.WEBSITE_FORM
    source_detail: str | None = Field(None, max_length=200)

    name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32, description="Any format; stored as E.164")
    email: EmailStr | None = None
    wa_id: str | None = Field(None, max_length=32)

    initial_inquiry: str | None = Field(None, max_length=4000)
    service_interest: str | None = Field(None, max_length=200)
    preferred_time_text: str | None = Field(None, max_length=200)
    preferred_time_at: datetime | None = None
    location_text: str | None = Field(None, max_length=200)

    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    consent_source: str | None = Field(None, max_length=120)

    # Anti-spam honeypot: humans never fill this; bots usually do.
    website: str | None = Field(None, max_length=200)

    @field_validator("name", "service_interest", "location_text", "initial_inquiry")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str | None) -> str | None:
        return v.lower() if v else None

    @field_validator("phone")
    @classmethod
    def _norm_phone(cls, v: str | None) -> str | None:
        try:
            return normalize_phone(v)
        except PhoneError as exc:
            raise ValueError(str(exc)) from exc


class LeadUpdate(BaseModel):
    """Payload for PATCH /api/leads/{lead_id}. Only provided fields change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None
    wa_id: str | None = Field(None, max_length=32)

    initial_inquiry: str | None = Field(None, max_length=4000)
    service_interest: str | None = Field(None, max_length=200)
    preferred_time_text: str | None = Field(None, max_length=200)
    preferred_time_at: datetime | None = None
    location_text: str | None = Field(None, max_length=200)

    stage: PipelineStage | None = None
    booking_status: BookingStatus | None = None
    consent_status: ConsentStatus | None = None
    consent_source: str | None = Field(None, max_length=120)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str | None) -> str | None:
        return v.lower() if v else None

    @field_validator("phone")
    @classmethod
    def _norm_phone(cls, v: str | None) -> str | None:
        try:
            return normalize_phone(v)
        except PhoneError as exc:
            raise ValueError(str(exc)) from exc


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: LeadSource
    source_detail: str | None
    stage: PipelineStage

    name: str | None
    phone_e164: str | None
    email: str | None
    wa_id: str | None

    initial_inquiry: str | None
    service_interest: str | None
    preferred_time_text: str | None
    preferred_time_at: datetime | None
    location_text: str | None

    booking_status: BookingStatus | None
    consent_status: ConsentStatus

    score: int | None
    classification: LeadClassification | None
    score_explanation: dict | None
    missing_info: list | None
    recommended_action: str | None
    scored_at: datetime | None

    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None
    utm_term: str | None

    campaign_id: uuid.UUID | None
    contact_id: uuid.UUID | None

    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None


class LeadListResponse(BaseModel):
    items: list[LeadRead]
    total: int
    limit: int
    offset: int


class ScoreResponse(BaseModel):
    lead_id: uuid.UUID
    score: int
    classification: LeadClassification
    explanation: dict
    missing_info: list[str]
    recommended_action: str
