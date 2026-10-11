"""Operational records: bookings, follow-up jobs, automation runs, audit logs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, UUIDMixin
from app.db.enums import BookingStatus, JobStatus, JobType, RunStatus
from app.db.models.crm import JSONType, _enum_col


class Booking(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bookings"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    service: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Requested = what the customer asked for. Scheduled = what staff confirmed.
    requested_time_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[BookingStatus] = mapped_column(
        _enum_col(BookingStatus, "booking_status"),
        default=BookingStatus.REQUESTED,
        nullable=False,
    )
    price_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)

    # A booking is only CONFIRMED once a human verifies it.
    verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_bookings_lead_id", "lead_id"),
        Index("ix_bookings_status", "status"),
        Index("ix_bookings_scheduled_at", "scheduled_at"),
        CheckConstraint(
            "status <> 'CONFIRMED' OR verified = true",
            name="confirmed_requires_verification",
        ),
    )


class FollowUpJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "follow_up_jobs"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[JobType] = mapped_column(_enum_col(JobType, "job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _enum_col(JobStatus, "job_status"), default=JobStatus.SCHEDULED, nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # Prevents the same reminder being enqueued twice for the same reason.
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_follow_up_jobs_idempotency_key"),
        Index("ix_follow_up_jobs_status_due_at", "status", "due_at"),
        Index("ix_follow_up_jobs_lead_id", "lead_id"),
    )


class AutomationRun(UUIDMixin, Base):
    __tablename__ = "automation_runs"

    run_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        _enum_col(RunStatus, "run_status"), default=RunStatus.RUNNING, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_automation_runs_run_type_started_at", "run_type", "started_at"),
    )


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    actor: Mapped[str] = mapped_column(String(200), default="system", nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_data: Mapped[dict | None] = mapped_column("before", JSONType, nullable=True)
    after_data: Mapped[dict | None] = mapped_column("after", JSONType, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )
