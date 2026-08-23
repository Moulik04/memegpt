"""
nlp/text_moderation.py — the text equivalent of uploads/moderation.py's
image content-safety gate, for Make's user-typed captions (the one surface
where caption text never passes through an LLM at all before landing on a
public meme). Same fail-closed contract: missing config, a provider error,
or an unparseable response are all treated as a failed check, never a
silent pass-through.
"""

from __future__ import annotations

import httpx
import pytest

from config import Settings
from nlp.text_moderation import ModerationResult, moderate_text


def _settings(groq_api_key: str = "fake-key") -> Settings:
    return Settings(_env_file=None, groq_api_key=groq_api_key)


def _mock_groq_client(handler):
    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    return fake_client


async def test_blank_text_is_safe_without_a_network_call(monkeypatch):
    import nlp.text_moderation as tm

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank text must never reach the provider")

    monkeypatch.setattr(tm, "get_settings", lambda: _settings())
    monkeypatch.setattr(tm.httpx, "AsyncClient", _mock_groq_client(handler))

    result = await moderate_text("   ")

    assert result == ModerationResult(passed=True)


async def test_no_groq_key_fails_closed(monkeypatch):
    import nlp.text_moderation as tm

    monkeypatch.setattr(tm, "get_settings", lambda: _settings(groq_api_key=""))

    result = await moderate_text("hello world")

    assert result.passed is False
    assert result.category == "moderation_unavailable"


async def test_safe_response_passes(monkeypatch):
    import nlp.text_moderation as tm

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "SAFE"}}]})

    monkeypatch.setattr(tm, "get_settings", lambda: _settings())
    monkeypatch.setattr(tm.httpx, "AsyncClient", _mock_groq_client(handler))

    result = await moderate_text("Monday mood: coffee before words")

    assert result == ModerationResult(passed=True)


async def test_unsafe_response_returns_category(monkeypatch):
    import nlp.text_moderation as tm

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "UNSAFE: hate"}}]}
        )

    monkeypatch.setattr(tm, "get_settings", lambda: _settings())
    monkeypatch.setattr(tm.httpx, "AsyncClient", _mock_groq_client(handler))

    result = await moderate_text("some slur-laden caption")

    assert result.passed is False
    assert result.category == "hate"


async def test_unparseable_response_fails_closed(monkeypatch):
    import nlp.text_moderation as tm

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "uhh what"}}]})

    monkeypatch.setattr(tm, "get_settings", lambda: _settings())
    monkeypatch.setattr(tm.httpx, "AsyncClient", _mock_groq_client(handler))

    result = await moderate_text("caption text")

    assert result.passed is False
    assert result.category == "unparseable_response"


async def test_provider_error_fails_closed(monkeypatch):
    import nlp.text_moderation as tm

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    monkeypatch.setattr(tm, "get_settings", lambda: _settings())
    monkeypatch.setattr(tm.httpx, "AsyncClient", _mock_groq_client(handler))

    result = await moderate_text("caption text")

    assert result.passed is False
    assert result.category == "moderation_unavailable"
