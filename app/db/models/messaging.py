"""WhatsApp conversation + message records."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.enums import (
    ConversationStatus,
    MessageDirection,
    MessageStatus,
)
from app.db.models.crm import JSONType, _enum_col


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp", nullable=False)
    wa_conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        _enum_col(ConversationStatus, "conversation_status"),
        default=ConversationStatus.OPEN,
        nullable=False,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(default=0, nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conversations_contact_id", "contact_id"),
        Index("ix_conversations_last_message_at", "last_message_at"),
        UniqueConstraint("channel", "wa_conversation_id", name="uq_conversations_channel_wa_id"),
    )


class Message(UUIDMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(
        _enum_col(MessageDirection, "message_direction"), nullable=False
    )
    wa_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MessageStatus] = mapped_column(
        _enum_col(MessageStatus, "message_status"),
        default=MessageStatus.RECEIVED,
        nullable=False,
    )
    is_automated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("wa_message_id", name="uq_messages_wa_message_id"),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_messages_direction", "direction"),
    )
