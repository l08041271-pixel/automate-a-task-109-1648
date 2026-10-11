"""Shared domain enums.

Used by both SQLAlchemy models (stored as VARCHAR + CHECK) and Pydantic
schemas so the API and DB never disagree about allowed values.
"""
from __future__ import annotations

from enum import StrEnum


class PipelineStage(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    LOST = "LOST"


#: Allowed forward/backward transitions for the CRM pipeline. `LOST` and
#: `COMPLETED` are terminal-ish but may be re-opened by an authorised user.
PIPELINE_TRANSITIONS: dict[PipelineStage, set[PipelineStage]] = {
    PipelineStage.NEW: {PipelineStage.CONTACTED, PipelineStage.QUALIFIED, PipelineStage.LOST},
    PipelineStage.CONTACTED: {PipelineStage.QUALIFIED, PipelineStage.BOOKED, PipelineStage.LOST},
    PipelineStage.QUALIFIED: {PipelineStage.BOOKED, PipelineStage.CONTACTED, PipelineStage.LOST},
    PipelineStage.BOOKED: {PipelineStage.COMPLETED, PipelineStage.QUALIFIED, PipelineStage.LOST},
    PipelineStage.COMPLETED: {PipelineStage.LOST},
    PipelineStage.LOST: {PipelineStage.NEW, PipelineStage.CONTACTED},
}


class LeadClassification(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class ConsentStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    OPTED_OUT = "OPTED_OUT"


class BookingStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class LeadSource(StrEnum):
    WEBSITE_FORM = "WEBSITE_FORM"
    LANDING_PAGE = "LANDING_PAGE"
    WHATSAPP_INBOUND = "WHATSAPP_INBOUND"
    SOCIAL = "SOCIAL"
    REFERRAL = "REFERRAL"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


class ConversationStatus(StrEnum):
    OPEN = "OPEN"
    PENDING = "PENDING"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    DRAFTED = "DRAFTED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"


class JobType(StrEnum):
    UNANSWERED_INQUIRY = "UNANSWERED_INQUIRY"
    INCOMPLETE_BOOKING = "INCOMPLETE_BOOKING"
    REQUESTED_LATER = "REQUESTED_LATER"
    APPOINTMENT_REMINDER = "APPOINTMENT_REMINDER"
    POST_APPOINTMENT_FEEDBACK = "POST_APPOINTMENT_FEEDBACK"


class JobStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class UserRole(StrEnum):
    OWNER = "OWNER"
    STAFF = "STAFF"
    VIEWER = "VIEWER"
