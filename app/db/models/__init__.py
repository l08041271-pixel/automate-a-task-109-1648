"""Import every model so ``Base.metadata`` is fully populated."""
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.crm import (
    Campaign,
    Contact,
    JSONType,
    Lead,
    LeadEvent,
    compute_dedupe_key,
)
from app.db.models.messaging import Conversation, Message
from app.db.models.ops import AuditLog, AutomationRun, Booking, FollowUpJob

__all__ = [
    "Base",
    "User",
    "Contact",
    "Campaign",
    "Lead",
    "LeadEvent",
    "Conversation",
    "Message",
    "Booking",
    "FollowUpJob",
    "AutomationRun",
    "AuditLog",
    "JSONType",
    "compute_dedupe_key",
]
