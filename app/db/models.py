"""SQLAlchemy 2 ORM-модели.

UUID PK, timezone-aware TIMESTAMPTZ, JSONB для сырых апдейтов.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    """Возвращает текущий момент в UTC c tz-info — единый стандарт хранения."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# chats
# ---------------------------------------------------------------------------


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# conversations
# ---------------------------------------------------------------------------

CONVERSATION_STATUS_ACTIVE = "ACTIVE"
CONVERSATION_STATUS_CLOSED = "CLOSED"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "chat_id",
            "status",
            name="uq_conversation_user_chat_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CONVERSATION_STATUS_ACTIVE
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_agent_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general"
    )
    active_skill_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="chat"
    )
    active_model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default_balanced"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    chat: Mapped[Chat] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

MESSAGE_DIRECTION_INBOUND = "inbound"
MESSAGE_DIRECTION_OUTBOUND = "outbound"
MESSAGE_DIRECTION_SYSTEM = "system"

MESSAGE_TYPE_TEXT = "text"
MESSAGE_TYPE_SYSTEM = "system"
MESSAGE_TYPE_ERROR = "error"


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conv_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_update_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# llm_requests
# ---------------------------------------------------------------------------

LLM_REQUEST_STATUS_STARTED = "started"
LLM_REQUEST_STATUS_SUCCESS = "success"
LLM_REQUEST_STATUS_ERROR = "error"


class LLMRequest(Base):
    __tablename__ = "llm_requests"
    __table_args__ = (
        Index("ix_llm_requests_conv_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, default="chat")
    model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default_balanced"
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# processed_updates
# ---------------------------------------------------------------------------


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_update_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


__all__ = [
    "Base",
    "User",
    "Chat",
    "Conversation",
    "Message",
    "LLMRequest",
    "ProcessedUpdate",
    "CONVERSATION_STATUS_ACTIVE",
    "CONVERSATION_STATUS_CLOSED",
    "MESSAGE_DIRECTION_INBOUND",
    "MESSAGE_DIRECTION_OUTBOUND",
    "MESSAGE_DIRECTION_SYSTEM",
    "MESSAGE_TYPE_TEXT",
    "MESSAGE_TYPE_SYSTEM",
    "MESSAGE_TYPE_ERROR",
    "LLM_REQUEST_STATUS_STARTED",
    "LLM_REQUEST_STATUS_SUCCESS",
    "LLM_REQUEST_STATUS_ERROR",
]
