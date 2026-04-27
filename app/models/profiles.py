"""Дефолтный набор LLM ModelProfile."""

from __future__ import annotations

from app.models.schemas import ModelProfile


DEFAULT_FAST = ModelProfile(
    id="default_fast",
    display_name="Default Fast",
    description="Быстрая и дешёвая модель — повседневный чат, короткие ответы.",
    provider="openrouter",
    model_name="google/gemini-2.0-flash-001",
    tier="cheap",
    supports_streaming=True,
    default_temperature=0.7,
    max_output_tokens=2048,
    enabled=True,
)


DEFAULT_BALANCED = ModelProfile(
    id="default_balanced",
    display_name="Default Balanced",
    description="Сбалансированная модель — основной выбор по умолчанию.",
    provider="openrouter",
    model_name="openai/gpt-4.1-mini",
    tier="balanced",
    supports_streaming=True,
    default_temperature=0.7,
    max_output_tokens=4096,
    enabled=True,
)


CRYPTO_MODEL = ModelProfile(
    id="crypto_model",
    display_name="Crypto Analyst",
    description="Модель для криптоанализа: запросы про токены, протоколы, on-chain.",
    provider="openrouter",
    model_name="openai/gpt-4.1-mini",
    tier="balanced",
    supports_streaming=True,
    default_temperature=0.4,
    max_output_tokens=4096,
    enabled=True,
)


FINANCE_MODEL = ModelProfile(
    id="finance_model",
    display_name="Finance Analyst",
    description="Модель для классических финансов: акции, макро, ставки.",
    provider="openrouter",
    model_name="openai/gpt-4.1-mini",
    tier="balanced",
    supports_streaming=True,
    default_temperature=0.4,
    max_output_tokens=4096,
    enabled=True,
)


NEWS_MODEL = ModelProfile(
    id="news_model",
    display_name="News Reader",
    description="Лёгкая модель для пересказов новостей и быстрых сводок.",
    provider="openrouter",
    model_name="google/gemini-2.0-flash-001",
    tier="cheap",
    supports_streaming=True,
    default_temperature=0.3,
    max_output_tokens=2048,
    enabled=True,
)


DEVOPS_MODEL = ModelProfile(
    id="devops_model",
    display_name="DevOps / Infra",
    description="Модель для DevOps/инфры: bash, Docker, k8s, CI/CD, Linux.",
    provider="openrouter",
    model_name="openai/gpt-4.1-mini",
    tier="balanced",
    supports_streaming=True,
    default_temperature=0.2,
    max_output_tokens=4096,
    enabled=True,
)


ALL_MODELS: list[ModelProfile] = [
    DEFAULT_FAST,
    DEFAULT_BALANCED,
    CRYPTO_MODEL,
    FINANCE_MODEL,
    NEWS_MODEL,
    DEVOPS_MODEL,
]


DEFAULT_MODEL_ID = DEFAULT_BALANCED.id

__all__ = [
    "ALL_MODELS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_FAST",
    "DEFAULT_BALANCED",
    "CRYPTO_MODEL",
    "FINANCE_MODEL",
    "NEWS_MODEL",
    "DEVOPS_MODEL",
]
