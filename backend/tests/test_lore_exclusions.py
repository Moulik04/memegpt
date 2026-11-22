"""
Two things a Lore "another take" request relies on, and the errors around
them:

- LoreRequest.exclude_templates rules templates out for the whole request.
  Only known ids count, each once, at most MAX_EXCLUDED_TEMPLATES of them.
  A pick that lands on one anyway is reported with code "no_fresh_template"
  so the browser can keep the meme it already shows.
- A failure the visitor can't act on never carries the exception's text,
  which can name server paths.
"""

from __future__ import annotations

import io
import json

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import routers.generate as generate_router
from main import app
from nlp.text_moderation import ModerationResult
from routers.chat import _TURN_FAILED, MAX_EXCLUDED_TEMPLATES
from schemas import IntentResponse
from storage import SavedMeme
from uploads.safe_ingest import CleanImage

_KNOWN = [f"template_{i}" for i in range(15)] + ["drake", "this_is_fine"]
_SERVER_PATH = "/srv/app/backend/templates/drake.jpg"


def _parse_sse_events(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in raw_text.splitlines() if line.startswith("data: ")]


async def _fake_compose_meme(template_id, texts):
    return SavedMeme(meme_id=f"stub-{template_id}", url=f"/static/generated/stub-{template_id}.png", path=None)


def _picking(template_id: str, seen: list):
    async def fake_parse_intent(
        user_message, avoid_templates=None, loved_templates=None, hated_templates=None,
        lexicon=None, exclude_templates=None,
    ):
        seen.append(exclude_templates)
        return IntentResponse(template_id=template_id, texts={"top_text": "a"}, reasoning="test stub")

    return fake_parse_intent


@pytest.fixture(autouse=True)
def _known_templates(monkeypatch):
    monkeypatch.setattr("routers.chat.list_template_ids", lambda: list(_KNOWN))
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)


async def _post_lore(body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/lore/", json={"message": "the group chat lost it", **body})


async def test_exclusions_reach_the_pick_known_once_and_capped(monkeypatch):
    seen: list = []
    monkeypatch.setattr("routers.chat.parse_intent", _picking("drake", seen))

    asked = ["not_a_template", "template_0", "template_0"] + [f"template_{i}" for i in range(1, 15)]
    resp = await _post_lore({"exclude_templates": asked})

    assert resp.status_code == 200
    assert seen == [[f"template_{i}" for i in range(MAX_EXCLUDED_TEMPLATES)]]
    assert [e["type"] for e in _parse_sse_events(resp.text)][-1] == "batch_done"


async def test_only_unknown_exclusions_are_as_good_as_none(monkeypatch):
    seen: list = []
    monkeypatch.setattr("routers.chat.parse_intent", _picking("drake", seen))

    resp = await _post_lore({"exclude_templates": ["not_a_template"]})

    assert resp.status_code == 200
    assert seen == [None]


async def test_without_exclusions_nothing_is_ruled_out(monkeypatch):
    seen: list = []
    monkeypatch.setattr("routers.chat.parse_intent", _picking("drake", seen))

    resp = await _post_lore({})

    assert resp.status_code == 200
    assert seen == [None]


async def test_a_pick_on_an_excluded_template_is_named_and_not_rendered(monkeypatch):
    monkeypatch.setattr("routers.chat.parse_intent", _picking("drake", []))

    resp = await _post_lore({"exclude_templates": ["drake"], "meme_count": 1})
    events = _parse_sse_events(resp.text)

    assert not [e for e in events if e["type"] == "done"]
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "no_fresh_template"
    assert "different template" in errors[0]["message"]
    assert events[-1]["succeeded"] == 0


async def test_an_oversized_exclusion_list_is_refused():
    resp = await _post_lore({"exclude_templates": ["drake"] * 51})
    assert resp.status_code == 422


# --- No exception text in what the visitor is sent.


async def test_a_failed_pick_sends_the_fixed_message(monkeypatch):
    async def broken_parse_intent(user_message, **kwargs):
        raise RuntimeError(f"could not open {_SERVER_PATH}")

    monkeypatch.setattr("routers.chat.parse_intent", broken_parse_intent)

    resp = await _post_lore({})
    errors = [e for e in _parse_sse_events(resp.text) if e["type"] == "error"]

    assert [e["message"] for e in errors] == [_TURN_FAILED]
    assert "/srv/" not in resp.text


async def test_a_missing_template_file_sends_the_fixed_message(monkeypatch):
    async def missing_file(template_id, texts):
        raise FileNotFoundError(_SERVER_PATH)

    monkeypatch.setattr("routers.chat.parse_intent", _picking("drake", []))
    monkeypatch.setattr("routers.chat.compose_meme", missing_file)

    resp = await _post_lore({})
    errors = [e for e in _parse_sse_events(resp.text) if e["type"] == "error"]

    assert [e["message"] for e in errors] == [_TURN_FAILED]
    assert "/srv/" not in resp.text


async def test_a_failed_canvas_render_sends_the_fixed_message(monkeypatch):
    async def fake_safe_ingest(upload):
        return CleanImage(
            image=Image.new("RGB", (10, 10)), width=10, height=10,
            content_type="image/jpeg", source_filename=upload.filename,
        )

    async def fake_captions(image, user_text=None):
        return {"top_text": "A", "bottom_text": "B"}

    async def broken_render(image, texts):
        raise OSError(f"cannot write {_SERVER_PATH}")

    monkeypatch.setattr("routers.chat.safe_ingest", fake_safe_ingest)
    monkeypatch.setattr("routers.chat.generate_canvas_captions", fake_captions)
    monkeypatch.setattr("routers.chat.compose_meme_on_image", broken_render)

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/chat/image/",
            files=[("images", ("photo.jpg", buf.getvalue(), "image/jpeg"))],
            data={"mode": "canvas"},
        )

    assert resp.status_code == 200
    assert "/srv/" not in resp.text
    assert _TURN_FAILED in resp.text


async def test_make_with_a_missing_template_file_names_no_path(monkeypatch):
    async def fake_moderate_text(text):
        return ModerationResult(passed=True)

    async def missing_file(**kwargs):
        raise FileNotFoundError(_SERVER_PATH)

    monkeypatch.setattr(generate_router, "moderate_text", fake_moderate_text)
    monkeypatch.setattr(generate_router, "compose_meme", missing_file)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/generate/", json={"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}},
        )

    assert resp.status_code == 404
    assert "/srv/" not in resp.text
