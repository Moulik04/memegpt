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
from httpx import ASGITransport, AsyncClient

import db
from auth import VerifiedUser, get_verified_user
from config import Settings
from main import app


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


# --- POST /auth/link-anon — Growth Phase H, Stage 2 ---


async def _post_link_anon(headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/auth/link-anon", headers=headers or {})


async def test_link_anon_with_no_anon_header_is_not_migrated(monkeypatch):
    monkeypatch.setattr(
        "routers.auth.get_verified_user",
        lambda request: _resolved(VerifiedUser(user_id="user-1", email=None)),
    )

    resp = await _post_link_anon()

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "migrated": False}


async def test_link_anon_with_unverified_token_is_not_migrated(monkeypatch):
    monkeypatch.setattr("routers.auth.get_verified_user", lambda request: _resolved(None))

    resp = await _post_link_anon(headers={"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "migrated": False}


async def test_link_anon_with_both_ids_calls_migration_and_reports_true(monkeypatch):
    monkeypatch.setattr(
        "routers.auth.get_verified_user",
        lambda request: _resolved(VerifiedUser(user_id="user-1", email=None)),
    )
    calls = []

    async def fake_migrate(anon_user_id, user_id):
        calls.append((anon_user_id, user_id))
        return 3

    monkeypatch.setattr(db, "migrate_anon_data_to_user", fake_migrate)

    resp = await _post_link_anon(headers={"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "migrated": True}
    assert calls == [("anon-1", "user-1")]


async def test_link_anon_with_nothing_to_migrate_reports_false(monkeypatch):
    monkeypatch.setattr(
        "routers.auth.get_verified_user",
        lambda request: _resolved(VerifiedUser(user_id="user-1", email=None)),
    )

    async def fake_migrate(anon_user_id, user_id):
        return 0

    monkeypatch.setattr(db, "migrate_anon_data_to_user", fake_migrate)

    resp = await _post_link_anon(headers={"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "migrated": False}


async def _resolved(value):
    """Wraps a plain value as an awaitable — lets a lambda stand in for an
    async function when monkeypatching get_verified_user."""
    return value
