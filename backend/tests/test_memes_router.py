"""
GET /memes/{id} — Growth Phase B share pages. Covers: 404 with no
DATABASE_URL configured (db.fetch_meme returns None, same as a genuinely
missing id — no distinction leaked to the caller), the response shape
(url + template_name only, never captions/situation text), and canvas-mode
memes (template_id=None) correctly returning template_name=None rather
than erroring.
"""

from __future__ import annotations

import db
from httpx import ASGITransport, AsyncClient
from main import app


async def _get_meme(meme_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/memes/{meme_id}")


async def test_unknown_id_404s(monkeypatch):
    async def fake_fetch_meme(meme_id):
        return None

    monkeypatch.setattr(db, "fetch_meme", fake_fetch_meme)
    resp = await _get_meme("doesnotexist")
    assert resp.status_code == 404


async def test_no_database_url_also_404s_not_500(monkeypatch):
    """db.fetch_meme already returns None gracefully with no DATABASE_URL
    configured (see test_db.py) — this confirms the router surfaces that
    as the same 404 a genuinely-missing id gets, not a crash."""
    async def fake_fetch_meme(meme_id):
        return None  # what db.fetch_meme actually returns with no pool

    monkeypatch.setattr(db, "fetch_meme", fake_fetch_meme)
    resp = await _get_meme("anything")
    assert resp.status_code == 404


async def test_known_id_returns_url_and_template_name(monkeypatch):
    async def fake_fetch_meme(meme_id):
        assert meme_id == "abc1234567"
        return {"id": "abc1234567", "url": "https://example.com/x.png", "template_id": "drake"}

    monkeypatch.setattr(db, "fetch_meme", fake_fetch_meme)
    monkeypatch.setattr(
        "routers.memes.get_template_record",
        lambda tid: {"name": "Drake Hotline Bling"},
    )

    resp = await _get_meme("abc1234567")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"url": "https://example.com/x.png", "template_name": "Drake Hotline Bling"}


async def test_canvas_mode_meme_has_no_template_name(monkeypatch):
    async def fake_fetch_meme(meme_id):
        return {"id": "abc1234567", "url": "https://example.com/x.png", "template_id": None}

    monkeypatch.setattr(db, "fetch_meme", fake_fetch_meme)
    resp = await _get_meme("abc1234567")
    assert resp.status_code == 200
    assert resp.json() == {"url": "https://example.com/x.png", "template_name": None}


async def test_response_never_includes_captions_or_situation_text(monkeypatch):
    """Privacy rule check — even if db.fetch_meme somehow returned extra
    fields, the response_model (SharedMemeResponse) only has url and
    template_name, so nothing else could leak through."""
    async def fake_fetch_meme(meme_id):
        return {
            "id": "abc1234567",
            "url": "https://example.com/x.png",
            "template_id": "drake",
            "situation_text": "this should never appear in the response",
        }

    monkeypatch.setattr(db, "fetch_meme", fake_fetch_meme)
    monkeypatch.setattr("routers.memes.get_template_record", lambda tid: None)

    resp = await _get_meme("abc1234567")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"url", "template_name"}
