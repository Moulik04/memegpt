"""
POST /chat/image/ — multi-image batch handling: moderation-failure aborts
the whole request, non-safety UploadRejected on one image just drops it,
and an explicit meme_count forces the segmented context count.

Drives the real FastAPI app via httpx's ASGI transport (no real network).
safe_ingest, describe_image, and parse_intent are monkeypatched so these
tests are fast, deterministic, and don't need a configured GROQ_API_KEY.
"""

from __future__ import annotations

import io
import json

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from main import app
from schemas import IntentResponse, VisionDescription
from uploads.safe_ingest import CleanImage, ModerationRejected, UploadRejected


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


async def _fake_safe_ingest(upload):
    if upload.filename == "moderation_flagged.jpg":
        raise ModerationRejected(category="test_category")
    if upload.filename == "bad_upload.jpg":
        raise UploadRejected(reason="file_too_large")
    return CleanImage(
        image=Image.new("RGB", (10, 10)),
        width=10,
        height=10,
        content_type="image/jpeg",
        source_filename=upload.filename,
    )


async def _fake_describe_image(image, user_text=None):
    return VisionDescription(situation="a fake photo description")


async def _fake_parse_intent(user_message: str, avoid_templates=None, loved_templates=None, hated_templates=None) -> IntentResponse:
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={"public_face": "everything is fine", "inner_reality": user_message[:50]},
        reasoning="test stub",
    )


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    monkeypatch.setattr("routers.chat.safe_ingest", _fake_safe_ingest)
    monkeypatch.setattr("routers.chat.describe_image", _fake_describe_image)
    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)


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


async def test_one_moderation_flagged_image_aborts_whole_batch():
    events = await _post_images([
        ("clean.jpg", _tiny_jpeg_bytes()),
        ("moderation_flagged.jpg", _tiny_jpeg_bytes()),
    ])
    errors = [e for e in events if e.get("type") == "error"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(errors) == 1
    assert len(done_events) == 0
    assert "couldn't be processed" in errors[0]["message"]


async def test_one_upload_rejected_image_survivor_continues():
    events = await _post_images([
        ("clean.jpg", _tiny_jpeg_bytes()),
        ("bad_upload.jpg", _tiny_jpeg_bytes()),
    ])
    done_events = [e for e in events if e.get("type") == "done"]
    batch_done = [e for e in events if e.get("type") == "batch_done"]
    assert len(done_events) == 1
    assert batch_done[0]["total"] == 1
    assert batch_done[0]["succeeded"] == 1


async def test_all_images_upload_rejected_with_text_degrades_to_text_only():
    events = await _post_images(
        [("bad_upload.jpg", _tiny_jpeg_bytes())],
        message="waiting for my PR to get reviewed",
    )
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["template_used"] == "hide_the_pain_harold"


async def test_all_images_upload_rejected_no_text_specific_reason():
    # Non-safety UploadRejected reasons are safe to surface specifically —
    # unlike ModerationRejected, whose category is never echoed.
    events = await _post_images([("bad_upload.jpg", _tiny_jpeg_bytes())])
    errors = [e for e in events if e.get("type") == "error"]
    assert len(errors) == 1
    assert "10MB" in errors[0]["message"]


async def test_explicit_meme_count_forces_n_memes(monkeypatch):
    async def fake_call_llm(client, settings, messages, temperature=0.75):
        return '{"contexts": [{"situation": "only one moment found"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)

    events = await _post_images(
        [("clean.jpg", _tiny_jpeg_bytes())],
        meme_count=3,
    )
    done_events = [e for e in events if e.get("type") == "done"]
    batch_done = [e for e in events if e.get("type") == "batch_done"]
    assert len(done_events) == 3
    assert batch_done[0]["total"] == 3
    assert batch_done[0]["succeeded"] == 3
