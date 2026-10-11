"""Booking schemas. A booking can only be CONFIRMED once a human verifies it."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import BookingStatus


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID | None = None
    service: str | None = Field(None, max_length=200)
    location_text: str | None = Field(None, max_length=200)
    requested_time_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=15, le=480)
    price_amount: float | None = Field(None, ge=0)
    currency: str = Field("SAR", min_length=3, max_length=3)
    notes: str | None = Field(None, max_length=2000)


class BookingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=15, le=480)
    status: BookingStatus | None = None
    price_amount: float | None = Field(None, ge=0)
    service: str | None = Field(None, max_length=200)
    location_text: str | None = Field(None, max_length=200)
    # Verification is an explicit human act, recorded with who and when.
    verified: bool | None = None
    verified_by: str | None = Field(None, max_length=200)
    verification_notes: str | None = Field(None, max_length=2000)


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    service: str | None
    location_text: str | None
    requested_time_at: datetime | None
    scheduled_at: datetime | None
    duration_minutes: int | None
    status: BookingStatus
    price_amount: float | None
    currency: str
    verified: bool
    verified_by: str | None
    verified_at: datetime | None
    verification_notes: str | None
    created_at: datetime
    updated_at: datetime
