"""Tests for model registry."""

from __future__ import annotations

from app.models.registry import get_model_registry


def test_default_is_default_balanced() -> None:
    registry = get_model_registry()
    assert registry.default_id == "default_balanced"


def test_get_default_fast() -> None:
    registry = get_model_registry()
    model = registry.get("default_fast")
    assert model.id == "default_fast"
    assert model.tier == "cheap"


def test_crypto_and_news_models_exist() -> None:
    registry = get_model_registry()
    assert registry.get("crypto_model").id == "crypto_model"
    assert registry.get("news_model").id == "news_model"


def test_unknown_falls_back_to_default() -> None:
    registry = get_model_registry()
    model = registry.get("missing")
    assert model.id == "default_balanced"


def test_all_enabled_have_required_fields() -> None:
    registry = get_model_registry()
    for model in registry.list_enabled():
        assert model.id
        assert model.provider
        assert model.model_name
        assert model.display_name
        assert 0.0 <= model.default_temperature <= 2.0
        assert model.max_output_tokens is None or model.max_output_tokens > 0


def test_streaming_supported_on_all_default_models() -> None:
    registry = get_model_registry()
    for model in registry.list_enabled():
        assert model.supports_streaming is True
