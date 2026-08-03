"""
auth.py's get_verified_user() — Growth Phase H, Stage 1. Verifies a Supabase
bearer token by calling GET /auth/v1/user; must never raise and must always
degrade to "no signed-in user" (None) on any unconfigured/missing/invalid
input, matching identity.py's get_anon_user_id() contract. Uses
httpx.MockTransport (no real network), same convention as test_llm_client.py.
"""

from __future__ import annotations

import httpx
from fastapi import Request

from auth import get_verified_user
from config import Settings


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


def _settings(supabase_url: str = "https://project.supabase.co", anon_key: str = "") -> Settings:
    return Settings(_env_file=None, supabase_url=supabase_url, supabase_anon_key=anon_key)


async def test_unconfigured_supabase_url_returns_none(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(supabase_url=""))

    result = await get_verified_user(_request({"Authorization": "Bearer abc"}))

    assert result is None


async def test_missing_authorization_header_returns_none(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())

    result = await get_verified_user(_request())

    assert result is None


async def test_malformed_authorization_header_returns_none(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())

    result = await get_verified_user(_request({"Authorization": "NotBearer abc"}))

    assert result is None


async def test_non_200_response_returns_none(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid token"})

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", fake_client)

    result = await get_verified_user(_request({"Authorization": "Bearer bad-token"}))

    assert result is None


async def test_valid_token_returns_verified_user(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer good-token"
        return httpx.Response(200, json={"id": "user-123", "email": "a@example.com"})

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", fake_client)

    result = await get_verified_user(_request({"Authorization": "Bearer good-token"}))

    assert result is not None
    assert result.user_id == "user-123"
    assert result.email == "a@example.com"


async def test_response_missing_id_returns_none(monkeypatch):
    import auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"email": "a@example.com"})

    real_async_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", fake_client)

    result = await get_verified_user(_request({"Authorization": "Bearer good-token"}))

    assert result is None
