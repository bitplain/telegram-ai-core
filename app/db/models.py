"""SQLAlchemy 2 ORM-модели.

UUID PK, timezone-aware TIMESTAMPTZ, JSONB для сырых апдейтов.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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

    eth_balance: Mapped[float] = mapped_column(
        Numeric(36, 18),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    digest_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    eth_price_alerts: Mapped[list["EthPriceAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# eth_price_alerts — целевая цена ETH/USD для уведомления
# ---------------------------------------------------------------------------


class EthPriceAlert(Base):
    __tablename__ = "eth_price_alerts"
    __table_args__ = (
        Index("ix_eth_price_alerts_user_active", "user_id", "is_active"),
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
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    target_price_usd: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # "above" | "below"
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="eth_price_alerts")


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
CONVERSATION_STATUS_ARCHIVED = "ARCHIVED"

CONVERSATION_MODE_DEFAULT = "default"
CONVERSATION_MODE_AGENT = "agent"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversation_active_user_chat",
            "user_id",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
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
    active_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CONVERSATION_MODE_DEFAULT,
        server_default=CONVERSATION_MODE_DEFAULT,
    )
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
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


# ---------------------------------------------------------------------------
# app_settings — runtime-настройки, управляемые через admin /settings
# ---------------------------------------------------------------------------


class AppSetting(Base):
    """Runtime-настройки приложения (key/value) с опциональным шифрованием.

    Используемые ключи:
    - ``openrouter_api_key`` — переопределение ENV-ключа OpenRouter (encrypted,
      если задан SETTINGS_ENCRYPTION_KEY).
    - ``yandex_api_key`` — API-ключ Яндекс-провайдера (пока используется как
      сохраняемая заглушка для будущей интеграции).
    - ``model_override.<model_id>`` — переопределение OpenRouter slug-а для
      конкретного ModelProfile, например ``model_override.default_balanced``.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
    updated_by_telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )


# ---------------------------------------------------------------------------
# user_agent_settings — пользовательские override-ы prompt/model для агентов
# ---------------------------------------------------------------------------


class UserAgentSetting(Base):
    """User-scoped настройки агента.

    Настройки привязаны к Telegram user-id и agent_id:
    - ``custom_prompt`` заменяет system prompt агента для конкретного пользователя;
    - ``model_id`` переопределяет модель агента для конкретного пользователя.
    """

    __tablename__ = "user_agent_settings"
    __table_args__ = (
        UniqueConstraint(
            "telegram_user_id",
            "agent_id",
            name="uq_user_agent_settings_user_agent",
        ),
        Index("ix_user_agent_settings_telegram_user_id", "telegram_user_id"),
        Index("ix_user_agent_settings_agent_id", "agent_id"),
        Index("ix_user_agent_settings_model_id", "model_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)

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


__all__ = [
    "Base",
    "User",
    "EthPriceAlert",
    "Chat",
    "Conversation",
    "Message",
    "LLMRequest",
    "ProcessedUpdate",
    "AppSetting",
    "UserAgentSetting",
    "CONVERSATION_STATUS_ACTIVE",
    "CONVERSATION_STATUS_CLOSED",
    "CONVERSATION_MODE_DEFAULT",
    "CONVERSATION_MODE_AGENT",
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
