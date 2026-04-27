"""JSON-логирование с фильтрацией секретов.

Используется единая конфигурация для всех слоёв приложения:
- python-json-logger выдаёт строки JSON;
- кастомный фильтр маскирует значения чувствительных полей и URL.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

from pythonjsonlogger import jsonlogger

from app.config import get_settings

# ---------------------------------------------------------------------------
# Маскировка секретов
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api_?key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
)

_URL_KEYS = {"DATABASE_URL", "REDIS_URL", "database_url", "redis_url"}


def _looks_secret(key: str) -> bool:
    return any(p.search(key) for p in _SECRET_KEY_PATTERNS)


def _mask_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "***")
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:  # noqa: BLE001
        pass
    return url


class SecretsFilter(logging.Filter):
    """Маскирует значения чувствительных полей в record.__dict__ и в args.

    Это не полная санитизация всего сообщения (это бы сильно деградировало
    производительность), но она надёжно прячет значения, которые мы сами
    кладём через extra={"openrouter_api_key": ...}, а также любые URL вида
    postgres://user:pass@host.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        # 1) extra-поля, попадающие в record.__dict__
        for key, value in list(record.__dict__.items()):
            if key in _URL_KEYS and isinstance(value, str):
                record.__dict__[key] = _mask_url(value)
                continue
            if not isinstance(value, str):
                continue
            if _looks_secret(key):
                record.__dict__[key] = "***"

        # 2) Никогда не пропускать структурный args, если в нём словарь с секретами.
        if isinstance(record.args, dict):
            record.args = {
                k: ("***" if _looks_secret(k) else v) for k, v in record.args.items()
            }

        return True


class _JsonFormatter(jsonlogger.JsonFormatter):
    """Расширяем стандартный JsonFormatter полем timestamp в ISO-формате."""

    def add_fields(  # type: ignore[override]
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # python-json-logger заполняет required_fields из record.__dict__ —
        # для нестандартных полей (timestamp/level) кладёт None. Перезатираем
        # своими значениями всегда, без проверки на наличие ключа.
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name


_FMT = (
    "%(timestamp)s %(level)s %(name)s %(message)s "
    "%(module)s %(funcName)s %(lineno)d"
)


def setup_logging(level: str | None = None) -> None:
    """Настраивает корневой логгер на JSON-формат с фильтром секретов.

    Идемпотентно: повторный вызов не дублирует хендлеры.
    """
    settings = get_settings()
    log_level = (level or settings.LOG_LEVEL or "INFO").upper()

    root = logging.getLogger()
    # Сносим старые хендлеры, добавленные uvicorn-ом до lifespan, чтобы не было дублей.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter(_FMT, datefmt="%Y-%m-%dT%H:%M:%S%z"))
    handler.addFilter(SecretsFilter())
    handler.setLevel(log_level)

    root.addHandler(handler)
    root.setLevel(log_level)

    # Громкие логгеры в DEBUG не пускаем — даже если LOG_LEVEL=DEBUG.
    for noisy in ("httpcore", "httpx", "asyncio", "aiogram.event"):
        logging.getLogger(noisy).setLevel(max(logging.INFO, logging.getLogger().level))

    # Uvicorn своими корневыми хендлерами тоже забивает stdout — переключаем
    # их на наш handler, чтобы оставались JSON-логи.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(log_level)
