"""
POST /feedback/ — Growth Phase B fix: every rating (up AND down) now
records a feedback row via db.insert_feedback, not just up-votes silently
funneling into the few-shot examples store while down-votes vanished
entirely. Drives the real FastAPI app via httpx's ASGI transport.
"""

from __future__ import annotations

import db
from httpx import ASGITransport, AsyncClient
from main import app


async def _post_feedback(monkeypatch, **payload):
    calls = []

    async def fake_insert_feedback(meme_id, rating, conversation_id=None):
        calls.append((meme_id, rating, conversation_id))

    monkeypatch.setattr(db, "insert_feedback", fake_insert_feedback)

    body = {"template_id": "drake", "rating": "up", **payload}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/feedback/", json=body)
    return resp, calls


async def test_thumbs_down_now_records_feedback_row(monkeypatch):
    resp, calls = await _post_feedback(monkeypatch, rating="down", meme_id="abc1234567")
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0] == ("abc1234567", "down", None)


async def test_thumbs_up_also_records_feedback_row(monkeypatch):
    resp, calls = await _post_feedback(monkeypatch, rating="up", meme_id="abc1234567")
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0] == ("abc1234567", "up", None)


async def test_thumbs_up_with_message_also_upserts_few_shot_example(monkeypatch):
    async def fake_insert_feedback(meme_id, rating, conversation_id=None):
        pass

    monkeypatch.setattr(db, "insert_feedback", fake_insert_feedback)

    example_calls = []

    async def fake_upsert_example(user_message, template_id, texts):
        example_calls.append((user_message, template_id, texts))

    monkeypatch.setattr("routers.feedback.upsert_example", fake_upsert_example)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/feedback/",
            json={
                "template_id": "drake",
                "rating": "up",
                "meme_id": "abc1234567",
                "user_message": "waiting forever",
                "texts": {"top_text": "a", "bottom_text": "b"},
            },
        )

    assert resp.status_code == 200
    assert len(example_calls) == 1
    assert example_calls[0] == ("waiting forever", "drake", {"top_text": "a", "bottom_text": "b"})
