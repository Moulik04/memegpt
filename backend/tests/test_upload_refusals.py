"""
What a visitor is told when the safety check refuses a photo, and what is
counted about it.

  - the message says MemeGPT can't use the image and suggests describing it
    in words. It never says why;
  - each refused photo is counted once, under one of a fixed set of labels
    and the surface it came from. Whatever the model wrote after "UNSAFE:"
    never reaches the count or the log: it is free text and could say what
    was in the picture;
  - a photo that could not be checked (busy, daily budget) is not a refusal
    and is not counted as one.

No network call: the gate is stubbed at the route.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import telemetry
from main import app
from uploads.safe_ingest import CleanImage, ModerationBusy, ModerationOutOfBudget, ModerationRejected

_REFUSED = "MemeGPT can't use this image. Try describing it in words instead."

# What the model wrote after "UNSAFE:", by the name of the uploaded file.
_VERDICTS = {
    "violence.jpg": "violence",
    "sexual.jpg": "sexual",
    "chatty.jpg": "violence - a man in a red shirt holding a knife in a kitchen",
    "invented.jpg": "weapons",
    "unreadable.jpg": "unparseable_response",
    "provider_down.jpg": "moderation_unavailable",
}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


async def _fake_safe_ingest(upload):
    name = upload.filename
    if name == "busy.jpg":
        raise ModerationBusy()
    if name == "out_of_budget.jpg":
        raise ModerationOutOfBudget()
    if name in _VERDICTS:
        raise ModerationRejected(_VERDICTS[name])
    return CleanImage(
        image=Image.new("RGB", (10, 10)), width=10, height=10, content_type="image/jpeg", source_filename=name
    )


@pytest.fixture
def counted(monkeypatch) -> list[dict]:
    """Every (category, surface) added to the refusal counter."""
    monkeypatch.setattr("routers.chat.safe_ingest", _fake_safe_ingest)
    seen: list[dict] = []
    monkeypatch.setattr(
        telemetry.upload_refusals_total, "add", lambda amount, attributes=None: seen.append(dict(attributes))
    )
    return seen


async def _post_images(names: list[str], path: str = "/chat/image/") -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(path, files=[("images", (name, _jpeg(), "image/jpeg")) for name in names])
    assert resp.status_code == 200
    return [json.loads(line[len("data: "):]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _errors(events: list[dict]) -> list[str]:
    return [e["message"] for e in events if e.get("type") == "error"]


@pytest.mark.parametrize(
    "written_by_the_model,label",
    [
        ("violence", "violence"),
        ("Violence.", "violence"),
        ("  SEXUAL  ", "sexual"),
        ("minors", "minors"),
        ("hate", "hate"),
        ("unclear", "unclear"),
        ("violence - a man in a red shirt holding a knife", "violence"),
        ("a man in a red shirt holding a knife", "other"),
        ("weapons", "other"),
        ("", "other"),
        (None, "other"),
        ("unknown", "other"),
        ("unspecified", "other"),
        ("unparseable_response", "no_verdict"),
        ("moderation_unavailable", "check_failed"),
    ],
)
def test_a_refusal_is_counted_under_a_fixed_label(written_by_the_model, label):
    assert telemetry.upload_refusal_label(written_by_the_model) == label


def test_every_label_is_one_of_a_known_few():
    for text in ["violence", "anything at all", None, "sexual content involving x", "unparseable_response"]:
        assert telemetry.upload_refusal_label(text) in telemetry.UPLOAD_REFUSAL_LABELS


@pytest.mark.parametrize("path,surface", [("/chat/image/", "chat"), ("/lore/image/", "lore")])
async def test_a_refused_photo_gets_the_helpful_message_and_is_counted(counted, path, surface):
    events = await _post_images(["violence.jpg"], path)

    assert _errors(events) == [_REFUSED]
    assert counted == [{"category": "violence", "surface": surface}]


@pytest.mark.parametrize("name", sorted(_VERDICTS))
async def test_the_message_never_says_why(counted, name):
    assert _errors(await _post_images([name])) == [_REFUSED]


async def test_what_the_model_wrote_about_the_picture_is_not_counted_or_logged(counted, caplog):
    with caplog.at_level(logging.DEBUG):
        await _post_images(["chatty.jpg"])

    assert counted == [{"category": "violence", "surface": "chat"}]
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "upload_refused category=violence surface=chat" in logged
    for word in ("red shirt", "knife", "kitchen", "chatty.jpg"):
        assert word not in logged


async def test_each_refused_photo_in_an_upload_is_counted_once(counted):
    events = await _post_images(["clean.jpg", "violence.jpg", "sexual.jpg", "invented.jpg"])

    assert _errors(events) == [_REFUSED]
    assert sorted(c["category"] for c in counted) == ["other", "sexual", "violence"]


async def test_a_check_that_broke_is_told_apart_from_a_real_refusal(counted):
    """Both end in the same message, since the photo was not passed. The
    count is what shows how many refusals were about the picture at all."""
    await _post_images(["unreadable.jpg"])
    await _post_images(["provider_down.jpg"])

    assert [c["category"] for c in counted] == ["no_verdict", "check_failed"]


@pytest.mark.parametrize("name", ["busy.jpg", "out_of_budget.jpg"])
async def test_a_photo_that_could_not_be_checked_is_not_counted_as_refused(counted, name):
    events = await _post_images([name])

    assert _errors(events) != [_REFUSED]
    assert counted == []


async def test_a_refusal_beside_an_unchecked_photo_counts_only_the_refusal(counted):
    events = await _post_images(["busy.jpg", "violence.jpg"])

    assert _errors(events) == [_REFUSED]
    assert counted == [{"category": "violence", "surface": "chat"}]


async def test_a_photo_that_passes_is_not_counted(counted, monkeypatch):
    async def broken_describe(image, user_text=None):
        raise RuntimeError("stop here, the gate is what this test is about")

    monkeypatch.setattr("routers.chat.describe_image", broken_describe)

    await _post_images(["clean.jpg"])

    assert counted == []
