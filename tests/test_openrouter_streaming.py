"""Тесты OpenRouter streaming/SSE parsing."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.llm.openrouter_client import OpenRouterClient


def test_chunk_from_event_extracts_delta_content() -> None:
    chunk = OpenRouterClient._chunk_from_event(
        {"choices": [{"delta": {"content": "Привет"}, "finish_reason": None}]}
    )

    assert chunk is not None
    assert chunk.content_delta == "Привет"
    assert chunk.finish_reason is None


def test_chunk_from_event_skips_empty_service_chunk() -> None:
    assert OpenRouterClient._chunk_from_event(
        {"choices": [{"delta": {}, "finish_reason": None}]}
    ) is None


@pytest.mark.asyncio
async def test_stream_chat_completion_sends_stream_true_and_yields_text_chunks() -> None:
    requests: list[dict[str, Any]] = []

    class _Response:
        status_code = 200

        async def aiter_lines(self):
            events = [
                {"choices": [{"delta": {"content": "При"}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": "вет"}, "finish_reason": None}]},
            ]
            for event in events:
                yield "data: " + json.dumps(event)
            yield "data: [DONE]"

    class _StreamContext:
        async def __aenter__(self):
            return _Response()

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    class _Client:
        def stream(self, method: str, url: str, **kwargs: Any) -> _StreamContext:
            requests.append({"method": method, "url": url, "kwargs": kwargs})
            return _StreamContext()

    client = OpenRouterClient(api_key="sk-test", base_url="https://example.test")
    client._client = _Client()  # type: ignore[assignment]

    chunks = [
        chunk.content_delta
        async for chunk in client.stream_chat_completion(
            model="openai/test",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]

    assert chunks == ["При", "вет"]
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "/chat/completions"
    assert requests[0]["kwargs"]["json"]["stream"] is True
