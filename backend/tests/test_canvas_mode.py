"""
Phase 2 (Mode 2: canvas) — the user's own photo becomes the meme directly,
bypassing the catalog template-picking pipeline entirely. Covers mode
inference/override, per-image caption-failure drop, total-failure graceful
degrade, and that canvas mode never touches describe_image/parse_intent.
"""

from __future__ import annotations

import io
import json

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from image_processing.compositor import compose_meme_on_image
from main import app
from nlp.vision import infer_mode
from uploads.safe_ingest import CleanImage


def test_infer_mode_canvas_phrase():
    assert infer_mode("make this a meme") == "canvas"
    assert infer_mode("meme this please") == "canvas"


def test_infer_mode_default_context():
    assert infer_mode("waiting for my PR to get reviewed") == "context"
    assert infer_mode(None) == "context"


@pytest.mark.parametrize("size", [(400, 600), (600, 400), (500, 500)])
async def test_compose_meme_on_image_handles_any_aspect_ratio(size):
    """Portrait, landscape, and square inputs must all produce a valid PNG
    without crashing — arbitrary user photos have no guaranteed shape,
    unlike the hand-picked catalog templates compose_meme() works with."""
    image = Image.new("RGB", size, color="green")
    url = await compose_meme_on_image(image, {"top_text": "TOP CAPTION", "bottom_text": "BOTTOM CAPTION"})
    assert url.startswith("/static/generated/canvas_")
    assert url.endswith(".png")


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


async def _fake_safe_ingest(upload):
    return CleanImage(
        image=Image.new("RGB", (10, 10)),
        width=10,
        height=10,
        content_type="image/jpeg",
        source_filename=upload.filename,
    )


async def _never_called_describe_image(image, user_text=None):
    raise AssertionError("describe_image should not be called in canvas mode")


async def _never_called_parse_intent(user_message, avoid_templates=None):
    raise AssertionError("parse_intent should not be called in canvas mode")


def _parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


async def _post_images(files: list[tuple[str, bytes]], **form_fields) -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/chat/image/",
            files=[("images", (name, data, "image/jpeg")) for name, data in files],
            data={k: str(v) for k, v in form_fields.items() if v is not None},
        )
    assert resp.status_code == 200
    return _parse_sse_events(resp.text)


@pytest.fixture(autouse=True)
def _stub_ingest_and_never_context(monkeypatch):
    monkeypatch.setattr("routers.chat.safe_ingest", _fake_safe_ingest)
    monkeypatch.setattr("routers.chat.describe_image", _never_called_describe_image)
    monkeypatch.setattr("routers.chat.parse_intent", _never_called_parse_intent)


async def test_canvas_mode_produces_meme_with_null_template(monkeypatch):
    async def fake_captions(image, user_text=None):
        return {"top_text": "WHEN YOU TEST", "bottom_text": "CANVAS MODE"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", fake_captions)

    events = await _post_images([("photo.jpg", _tiny_jpeg_bytes())], mode="canvas")

    done_events = [e for e in events if e.get("type") == "done"]
    batch_done = [e for e in events if e.get("type") == "batch_done"]
    assert len(done_events) == 1
    assert done_events[0]["template_used"] is None
    assert done_events[0]["message"]["meme_url"].startswith("/static/generated/canvas_")
    assert batch_done[0]["total"] == 1
    assert batch_done[0]["succeeded"] == 1


async def test_canvas_mode_inferred_from_message_keyword(monkeypatch):
    async def fake_captions(image, user_text=None):
        return {"top_text": "A", "bottom_text": "B"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", fake_captions)

    # No explicit mode= override — inferred purely from the message wording.
    events = await _post_images([("photo.jpg", _tiny_jpeg_bytes())], message="make this a meme")

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["template_used"] is None


async def test_one_caption_failure_dropped_survivor_continues(monkeypatch):
    call_count = {"n": 0}

    async def flaky_captions(image, user_text=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return {"top_text": "OK", "bottom_text": "FINE"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", flaky_captions)

    events = await _post_images(
        [("photo1.jpg", _tiny_jpeg_bytes()), ("photo2.jpg", _tiny_jpeg_bytes())],
        mode="canvas",
    )

    done_events = [e for e in events if e.get("type") == "done"]
    batch_done = [e for e in events if e.get("type") == "batch_done"]
    assert len(done_events) == 1
    assert batch_done[0]["total"] == 1
    assert batch_done[0]["succeeded"] == 1


async def test_all_captions_fail_degrades_to_text_reply(monkeypatch):
    async def always_fails(image, user_text=None):
        return None

    monkeypatch.setattr("routers.chat.generate_canvas_captions", always_fails)

    events = await _post_images([("photo.jpg", _tiny_jpeg_bytes())], mode="canvas")

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["message"]["meme_url"] is None


async def test_two_images_canvas_mode_produces_two_memes(monkeypatch):
    async def fake_captions(image, user_text=None):
        return {"top_text": "TOP", "bottom_text": "BOTTOM"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", fake_captions)

    events = await _post_images(
        [("photo1.jpg", _tiny_jpeg_bytes()), ("photo2.jpg", _tiny_jpeg_bytes())],
        mode="canvas",
    )

    done_events = [e for e in events if e.get("type") == "done"]
    batch_done = [e for e in events if e.get("type") == "batch_done"]
    assert len(done_events) == 2
    assert batch_done[0]["total"] == 2
    assert batch_done[0]["succeeded"] == 2


async def test_invalid_mode_value_falls_back_to_inference(monkeypatch):
    async def fake_captions(image, user_text=None):
        return {"top_text": "A", "bottom_text": "B"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", fake_captions)

    # An invalid mode string should be ignored, falling through to
    # keyword inference on the message — "meme this" infers canvas.
    events = await _post_images(
        [("photo.jpg", _tiny_jpeg_bytes())],
        mode="not_a_real_mode",
        message="meme this",
    )

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["template_used"] is None
