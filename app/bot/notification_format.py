"""Форматирование краткой сводки по outbox-уведомлениям для Telegram."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.bot.renderers.telegram_text import escape_html


class _NotificationRow(Protocol):
    notification_type: str
    status: str
    retry_count: int
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None


def format_recent_notifications_text(rows: list[_NotificationRow]) -> str:
    """Без полного текста сообщения и без payload (только метаданные)."""
    if not rows:
        return "Последних уведомлений нет."

    lines = ["<b>Последние уведомления</b>", ""]
    for row in rows:
        err = ""
        if row.last_error:
            err = escape_html(row.last_error[:120])
            if len(row.last_error) > 120:
                err += "…"
        sent = row.sent_at.isoformat() if row.sent_at else "—"
        lines.append(
            f"• <code>{escape_html(row.notification_type)}</code> / "
            f"<b>{escape_html(row.status)}</b> "
            f"(retry {row.retry_count})\n"
            f"  created: {escape_html(row.created_at.isoformat())}\n"
            f"  sent: {escape_html(sent)}"
            + (f"\n  err: {err}" if err else "")
        )
    return "\n".join(lines)


__all__ = ["format_recent_notifications_text"]
