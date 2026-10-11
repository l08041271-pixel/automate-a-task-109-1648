"""Follow-up job schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.enums import JobStatus, JobType


class FollowUpJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    job_type: JobType
    status: JobStatus
    due_at: datetime
    attempts: int
    max_attempts: int
    last_error: str | None
    created_at: datetime


class RunReport(BaseModel):
    processed: int
    drafted: int
    skipped: int
    cancelled: int
    failed: int
    reasons: dict[str, int]
    ran_at: datetime
    note: str = "Drafts only — no message is sent to a customer by this run."
