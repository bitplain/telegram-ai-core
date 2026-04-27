"""SkillRouter: выбирает skill для входящего сообщения.

Приоритет:
1. Команда из текста (если первое слово начинается с / и совпадает с trigger_commands).
2. Активный skill из conversation.active_skill_id (если задан и существует).
3. Keyword matching по trigger_keywords (case-insensitive по подстроке слова).
4. Default 'chat'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.skills.registry import SkillRegistry, get_skill_registry
from app.skills.schemas import SkillProfile

# Команды Telegram могут идти с упоминанием бота: /skill@MyBot
_COMMAND_RE = re.compile(r"^/[a-zA-Z0-9_]+(?:@[a-zA-Z0-9_]+)?$")


@dataclass(slots=True)
class SkillResolution:
    """Результат маршрутизации: выбранный skill, отметка о происхождении и
    очищенный от ведущей команды текст пользователя."""

    skill: SkillProfile
    matched_by: str  # "command" | "active" | "keyword" | "default"
    cleaned_text: str
    matched_command: str | None = None


def _strip_bot_mention(command: str) -> str:
    """`/crypto@MyBot` → `/crypto`."""
    return command.split("@", 1)[0]


class SkillRouter:
    """Решает, какой skill применить."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or get_skill_registry()
        self._command_to_skill: dict[str, SkillProfile] = {}
        for skill in self._registry.list_enabled():
            for cmd in skill.trigger_commands:
                normalized = _strip_bot_mention(cmd).lower()
                self._command_to_skill[normalized] = skill

    def resolve(
        self,
        *,
        text: str | None,
        active_skill_id: str | None,
    ) -> SkillResolution:
        """Возвращает SkillResolution по тексту и активному skill пользователя."""
        raw = (text or "").strip()

        # 1) Команда — если первое слово выглядит как команда.
        if raw:
            first_word, _, remainder = raw.partition(" ")
            if first_word.startswith("/") and _COMMAND_RE.match(first_word):
                normalized = _strip_bot_mention(first_word).lower()
                skill = self._command_to_skill.get(normalized)
                if skill is not None:
                    return SkillResolution(
                        skill=skill,
                        matched_by="command",
                        cleaned_text=remainder.strip(),
                        matched_command=normalized,
                    )

        # 2) Активный skill из conversation.
        if active_skill_id:
            active = self._registry.get_or_none(active_skill_id)
            if active is not None and active.enabled:
                return SkillResolution(
                    skill=active,
                    matched_by="active",
                    cleaned_text=raw,
                )

        # 3) Keyword matching.
        if raw:
            lowered = raw.lower()
            for skill in self._registry.list_enabled():
                if skill.id == self._registry.default_id:
                    continue
                for keyword in skill.trigger_keywords:
                    kw = keyword.lower().strip()
                    if not kw:
                        continue
                    # Граничная проверка по slovo, чтобы "btc" не матчилось внутри "abct".
                    pattern = rf"(?:^|\W){re.escape(kw)}(?:$|\W)"
                    if re.search(pattern, lowered):
                        return SkillResolution(
                            skill=skill,
                            matched_by="keyword",
                            cleaned_text=raw,
                        )

        # 4) Default.
        default_skill = self._registry.get(self._registry.default_id)
        return SkillResolution(
            skill=default_skill,
            matched_by="default",
            cleaned_text=raw,
        )


def get_skill_router() -> SkillRouter:
    """Возвращает свежий router (lightweight)."""
    return SkillRouter()


__all__ = ["SkillRouter", "SkillResolution", "get_skill_router"]
