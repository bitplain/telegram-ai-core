"""Форматирование memories для system prompt (без дублирования message history)."""

from __future__ import annotations

from app.db.models import MEMORY_SCOPE_AGENT, MEMORY_SCOPE_GLOBAL, Memory


def format_memory_system_suffix(memories: list[Memory], *, max_items: int = 20) -> str:
    if not memories:
        return ""
    lines: list[str] = []
    for m in memories[:max_items]:
        tag = (
            "global"
            if m.scope == MEMORY_SCOPE_GLOBAL
            else f"agent:{m.agent_id or ''}"
        )
        lines.append(f"• [{tag}] {m.content}")
    return (
        "\n\n---\n"
        "Сохранённая долговременная память (команда /remember и /memory add_agent; "
        "это не история чата):\n"
        + "\n".join(lines)
    )
