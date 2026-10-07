"""
DELETE /me — "Forget me". Router-level: what identity it acts on, the order
it removes things in, and that no failure is ever reported as success. What
the SQL actually removes is covered against a real Postgres in
test_data_lifecycle.py; FakePool-style tests cannot see a foreign-key
violation, which is how this route once failed for every signed-in user
with saved history while its tests stayed green.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import db
import storage
from auth import VerifiedUser
from main import app

_MEME = ("abc1234567", "https://pub.example/abc1234567.png")
_LATE_MEME = ("late765432", "https://pub.example/late765432.png")


async def _resolved(value):
    return value


async def _forget(headers: dict | None = None):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete("/me", headers=headers or {})


@pytest.fixture
def calls(monkeypatch):
    """Records every storage and database call the route makes, in order."""
    log: list[tuple] = []

    async def fetch_identity_memes(anon_user_id, user_id):
        log.append(("fetch", anon_user_id, user_id))
        return [_MEME]

    async def delete_memes(memes):
        log.append(("storage", list(memes)))

    async def delete_identity_data(anon_user_id, user_id):
        log.append(("db", anon_user_id, user_id))
        return [_MEME]

    monkeypatch.setattr(db, "fetch_identity_memes", fetch_identity_memes)
    monkeypatch.setattr(storage, "delete_memes", delete_memes)
    monkeypatch.setattr(db, "delete_identity_data", delete_identity_data)
    monkeypatch.setattr("routers.me.get_verified_user", lambda request: _resolved(None))
    return log


def _sign_in(monkeypatch, user_id: str | None):
    value = VerifiedUser(user_id=user_id, email=None) if user_id else None
    monkeypatch.setattr("routers.me.get_verified_user", lambda request: _resolved(value))


async def test_signed_out_erases_by_anonymous_id_images_first(calls):
    resp = await _forget({"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert calls == [
        ("fetch", "anon-1", None),
        ("storage", [_MEME]),
        ("db", "anon-1", None),
        ("storage", []),
    ]


async def test_signed_in_erases_the_account_as_well(calls, monkeypatch):
    _sign_in(monkeypatch, "user-1")

    resp = await _forget({"X-MemeGPT-User": "anon-1", "Authorization": "Bearer good"})

    assert resp.status_code == 200
    assert ("fetch", "anon-1", "user-1") in calls
    assert ("db", "anon-1", "user-1") in calls


async def test_signed_in_without_an_anonymous_id_still_erases_the_account(calls, monkeypatch):
    _sign_in(monkeypatch, "user-1")

    resp = await _forget({"Authorization": "Bearer good"})

    assert resp.status_code == 200
    assert ("db", None, "user-1") in calls


async def test_a_sign_in_that_does_not_verify_is_refused_not_downgraded(calls):
    """Erasing only the anonymous half and answering "ok" would look like
    success to someone who asked for their account's history to go."""
    resp = await _forget({"X-MemeGPT-User": "anon-1", "Authorization": "Bearer expired"})

    assert resp.status_code == 401
    assert "nothing was erased" in resp.json()["detail"]
    assert calls == []


async def test_no_identity_at_all_is_a_no_op(calls):
    resp = await _forget()

    assert resp.status_code == 200
    assert calls == []


async def test_storage_failure_is_reported_and_no_row_is_removed(calls, monkeypatch):
    async def failing_delete_memes(memes):
        raise storage.MemeDeleteError("1 stored image(s) could not be removed")

    monkeypatch.setattr(storage, "delete_memes", failing_delete_memes)

    resp = await _forget({"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 500
    assert "couldn't finish erasing" in resp.json()["detail"]
    assert not any(call[0] == "db" for call in calls)


async def test_database_failure_is_reported(calls, monkeypatch):
    async def failing_delete(anon_user_id, user_id):
        raise RuntimeError("foreign key violation")

    monkeypatch.setattr(db, "delete_identity_data", failing_delete)

    resp = await _forget({"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 500
    assert "couldn't finish erasing" in resp.json()["detail"]
    assert "foreign key" not in resp.text  # the cause is logged, not sent to the browser


async def test_a_meme_made_mid_erase_still_has_its_image_removed(calls, monkeypatch):
    async def delete_returns_one_more(anon_user_id, user_id):
        calls.append(("db", anon_user_id, user_id))
        return [_MEME, _LATE_MEME]

    monkeypatch.setattr(db, "delete_identity_data", delete_returns_one_more)

    resp = await _forget({"X-MemeGPT-User": "anon-1"})

    assert resp.status_code == 200
    assert calls[-1] == ("storage", [_LATE_MEME])
