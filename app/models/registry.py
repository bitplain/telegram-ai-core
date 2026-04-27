"""In-memory registry для LLM ModelProfile."""

from __future__ import annotations

import logging

from app.models.profiles import ALL_MODELS, DEFAULT_MODEL_ID
from app.models.schemas import ModelProfile

log = logging.getLogger(__name__)


class ModelRegistry:
    """Поиск и перечисление моделей по id.

    Реализован поверх dict, но интерфейс совместим с будущим переездом в БД.
    """

    def __init__(self, profiles: list[ModelProfile] | None = None) -> None:
        items = profiles if profiles is not None else ALL_MODELS
        self._items: dict[str, ModelProfile] = {p.id: p for p in items}
        self._default_id = DEFAULT_MODEL_ID

    def get(self, model_id: str | None) -> ModelProfile:
        """Возвращает модель по id. Если id неизвестен — default + warning."""
        if model_id and model_id in self._items:
            return self._items[model_id]
        if model_id:
            log.warning(
                "Unknown model_id '%s' — falling back to default '%s'",
                model_id,
                self._default_id,
            )
        return self._items[self._default_id]

    def get_or_none(self, model_id: str) -> ModelProfile | None:
        return self._items.get(model_id)

    def list_enabled(self) -> list[ModelProfile]:
        return [p for p in self._items.values() if p.enabled]

    def list_all(self) -> list[ModelProfile]:
        return list(self._items.values())

    @property
    def default_id(self) -> str:
        return self._default_id


_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    """Singleton registry."""
    return _registry


__all__ = ["ModelRegistry", "get_model_registry"]
