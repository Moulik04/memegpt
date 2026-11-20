"""
Lore's opt-in source lines. With include_source_lines the segmentation model
sees each pasted line numbered and names the lines every moment draws on;
the backend keeps only numbers that point at real lines and sends them in
the plan event. Without it, every prompt and event is exactly what it was
before source lines existed (pinned by fixtures/segmentation_prompts_golden.json,
recorded from the code before this change).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import daily_quota
import nlp.segmentation as segmentation
from config import Settings
from main import app
from nlp.segmentation import resolve_contexts, segment_contexts
from schemas import IntentResponse

_GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "segmentation_prompts_golden.json").read_text())

_PASTE = (
    "maya: flight delayed again. third time.\n"
    "leo: that gate has your mail now\n"
    "\n"
    "june: this meeting could've been an email\n"
    "  you: it has a follow-up meeting\n"
    "[11/18/26, 9:41 PM] maya: phone's at 1%"
)
_PASTE_LINES = [1, 2, 4, 5, 6]  # line 3 is blank


def _scripted_llm(*replies):
    calls: list[dict] = []
    pending = [r if isinstance(r, str) else json.dumps(r) for r in replies]

    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None, **kwargs):
        calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return pending.pop(0)

    return fake_call_llm, calls


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    monkeypatch.setattr(segmentation, "get_settings", lambda: Settings(_env_file=None))


def _use(monkeypatch, *replies):
    fake, calls = _scripted_llm(*replies)
    monkeypatch.setattr(segmentation, "call_llm", fake)
    return calls


# --- Flag off: nothing changes ------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(_GOLDEN))
async def test_without_the_flag_the_model_sees_exactly_what_it_did_before(monkeypatch, scenario):
    golden = _GOLDEN[scenario]
    inputs = golden["inputs"]
    calls = _use(monkeypatch, *inputs["replies"])

    result = await segment_contexts(
        inputs["text"], inputs["image_descriptions"], inputs["requested_count"], inputs["lexicon"]
    )

    assert calls == golden["calls"]
    assert [{"situation": c.situation, "take_of": c.take_of} for c in result] == golden["result"]
    assert all(c.source_lines is None for c in result)


async def test_without_the_flag_the_fast_path_has_no_source_lines():
    [context] = await resolve_contexts("my flight got delayed again")
    assert context.source_lines is None


# --- What the model sees with the flag ---------------------------------------


async def test_numbered_material_and_prompt(monkeypatch):
    calls = _use(monkeypatch, {"contexts": [{"situation": "a", "lines": [1]}, {"situation": "b", "lines": [4]}]})

    await segment_contexts(_PASTE, number_lines=True)

    system, user = calls[0]["messages"]
    assert user["content"] == (
        "Message:\n"
        "1 | maya: flight delayed again. third time.\n"
        "2 | leo: that gate has your mail now\n"
        "4 | june: this meeting could've been an email\n"
        "5 |   you: it has a follow-up meeting\n"
        "6 | [11/18/26, 9:41 PM] maya: phone's at 1%"
    )
    assert segmentation._SOURCE_LINES_INSTRUCTION in system["content"]
    assert segmentation._NUMBERED_FORMAT in system["content"]
    assert segmentation._PLAIN_FORMAT not in system["content"]
    assert calls[0]["max_tokens"] > _GOLDEN["auto_count_text"]["calls"][0]["max_tokens"]


async def test_the_more_request_lists_found_moments_with_dashes(monkeypatch):
    calls = _use(
        monkeypatch,
        {"contexts": [{"situation": "my flight got delayed a third time", "lines": [1, 2]}]},
        {"contexts": [{"situation": "my phone is at one percent and I keep texting", "lines": [6]}]},
    )

    result = await segment_contexts(_PASTE, requested_count=2, number_lines=True)

    system, user = calls[1]["messages"]
    assert user["content"].endswith("Already found:\n- my flight got delayed a third time")
    assert "\n1 | maya" in user["content"]
    assert segmentation._NUMBERED_FORMAT in system["content"]
    assert [c.source_lines for c in result] == [[1, 2], [6]]


# --- What the backend keeps ---------------------------------------------------


async def test_only_integers_pointing_at_real_lines_are_kept(monkeypatch):
    _use(monkeypatch, {"contexts": [
        {"situation": "flight", "lines": [2, 1, 3, 99, 0, -1, "4", 4.0, True, 2, None]},
        {"situation": "meeting", "lines": []},
        {"situation": "phone"},
        {"situation": "gate", "lines": "1, 2"},
        {"situation": "email", "lines": [7, 3]},
    ]})

    result = await segment_contexts(_PASTE, number_lines=True)

    assert [c.source_lines for c in result] == [[1, 2], None, None, None, None]


async def test_a_dropped_repeat_leaves_the_kept_moment_its_own_lines(monkeypatch):
    _use(monkeypatch, {"contexts": [
        {"situation": "my flight got delayed again for the third time at the gate", "lines": [1]},
        {"situation": "my flight got delayed again, the third time, stuck at the gate", "lines": [1, 2]},
        {"situation": "a meeting that could have been an email", "lines": [4, 5]},
    ]})

    result = await segment_contexts(_PASTE, number_lines=True)

    assert [c.source_lines for c in result] == [[1], [4, 5]]


async def test_a_take_reuses_its_moments_lines(monkeypatch):
    _use(
        monkeypatch,
        {"contexts": [
            {"situation": "my flight got delayed a third time", "lines": [1, 2]},
            {"situation": "a meeting that could have been an email", "lines": [4, 5]},
        ]},
        {"contexts": []},
    )

    result = await segment_contexts(_PASTE, requested_count=4, number_lines=True)

    assert [c.take_of for c in result] == [None, None, 0, 1]
    assert [c.source_lines for c in result] == [[1, 2], [4, 5], [1, 2], [4, 5]]


# --- One context made from the whole paste ------------------------------------


async def test_text_only_fast_path_gets_every_non_blank_line():
    [context] = await resolve_contexts("maya: flight delayed\n\nleo: again?", number_lines=True)
    assert context.source_lines == [1, 3]


async def test_meme_count_one_fast_path_gets_every_non_blank_line():
    [context] = await resolve_contexts(_PASTE * 10, requested_count=1, number_lines=True)
    assert context.source_lines == [n for n, line in enumerate((_PASTE * 10).split("\n"), 1) if line.strip()]


async def test_fast_path_with_a_photo_gets_none():
    [context] = await resolve_contexts("look at this", ["a cat on a keyboard"], number_lines=True)
    assert context.source_lines is None


async def test_the_fallback_matches_the_fast_path(monkeypatch):
    _use(monkeypatch, "not json at all")
    [context] = await segment_contexts(_PASTE, number_lines=True)
    assert context.source_lines == _PASTE_LINES


async def test_the_fallback_with_a_photo_gets_none(monkeypatch):
    _use(monkeypatch, "not json at all")
    [context] = await segment_contexts(_PASTE, ["a cat on a keyboard"], requested_count=2, number_lines=True)
    assert context.source_lines is None


async def test_photo_only_lore_is_never_numbered(monkeypatch):
    golden = _GOLDEN["photos_only"]
    calls = _use(monkeypatch, *golden["inputs"]["replies"])

    result = await segment_contexts(None, golden["inputs"]["image_descriptions"], 2, number_lines=True)

    assert calls == golden["calls"]
    assert all(c.source_lines is None for c in result)


async def test_text_with_photos_numbers_only_the_text(monkeypatch):
    calls = _use(monkeypatch, {"contexts": [
        {"situation": "flight", "lines": [1]},
        {"situation": "cat", "lines": []},
    ]})

    result = await segment_contexts(_PASTE, ["a cat on a keyboard"], requested_count=2, number_lines=True)

    user = calls[0]["messages"][1]["content"]
    assert "1 | maya" in user
    assert user.endswith("\n\nPhoto 1: a cat on a keyboard")
    assert [c.source_lines for c in result] == [[1], None]


# --- The plan event -------------------------------------------------------------


async def _fake_parse_intent(user_message, **kwargs) -> IntentResponse:
    return IntentResponse(template_id="drake", texts={"rejected_option": "a", "approved_option": "b"}, reasoning="stub")


@pytest.fixture
def _stub_pick(monkeypatch):
    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)


async def _lore(body: dict) -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/lore/", json=body)
    assert resp.status_code == 200
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _plans(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "plan"]


async def test_one_moment_gets_a_plan_with_its_lines(_stub_pick):
    events = await _lore({"message": "maya: flight delayed\n\nleo: again?", "include_source_lines": True})

    [plan] = _plans(events)
    assert plan == {"type": "plan", "situations": ["maya: flight delayed\n\nleo: again?"], "total": 1,
                    "source_lines": [[1, 3]]}
    assert events[0] == plan


async def test_one_moment_without_the_flag_gets_no_plan(_stub_pick):
    events = await _lore({"message": "maya: flight delayed\n\nleo: again?"})
    assert _plans(events) == []


async def test_several_moments_with_takes(monkeypatch, _stub_pick):
    _use(
        monkeypatch,
        {"contexts": [
            {"situation": "my flight got delayed a third time", "lines": [1, 2]},
            {"situation": "a meeting that could have been an email", "lines": [4, 5]},
        ]},
        {"contexts": []},
    )

    [plan] = _plans(await _lore({"message": _PASTE, "meme_count": 3, "include_source_lines": True}))

    assert plan["take_of"] == [None, None, 0]
    assert plan["source_lines"] == [[1, 2], [4, 5], [1, 2]]


async def test_several_moments_without_the_flag_carry_no_source_lines(monkeypatch, _stub_pick):
    _use(monkeypatch, {"contexts": [
        {"situation": "my flight got delayed a third time", "lines": [1, 2]},
        {"situation": "a meeting that could have been an email", "lines": [4, 5]},
    ]})

    [plan] = _plans(await _lore({"message": _PASTE, "meme_count": 2}))

    assert plan == {"type": "plan", "situations": [
        "my flight got delayed a third time", "a meeting that could have been an email",
    ], "total": 2}


async def test_lines_are_numbered_on_the_text_after_the_cut(monkeypatch, _stub_pick):
    calls = _use(monkeypatch, {"contexts": [{"situation": "a", "lines": [1]}, {"situation": "b", "lines": [2]}]})
    limit = Settings(_env_file=None).max_dump_chars
    first = "x" * (limit - 10)
    message = f"{first}\nmaya: this second line runs past the cut\nleo: and this one is gone"

    await _lore({"message": message, "include_source_lines": True})

    cut = message[:limit]
    assert calls[0]["messages"][1]["content"] == f"Message:\n1 | {first}\n2 | {cut.split(chr(10))[1]}"


async def test_a_visitor_near_the_cap_gets_lines_trimmed_with_the_moments(monkeypatch, _stub_pick):
    monkeypatch.setattr(
        daily_quota, "get_settings",
        lambda: Settings(_env_file=None, daily_memes_per_browser=2, daily_memes_per_address=0),
    )
    _use(monkeypatch, {"contexts": [
        {"situation": "my flight got delayed a third time", "lines": [1, 2]},
        {"situation": "a meeting that could have been an email", "lines": [4, 5]},
        {"situation": "my phone is at one percent and I keep texting", "lines": [6]},
    ]})

    # Long enough to go through segmentation rather than the fast path.
    message = _PASTE + "\nleo: " + "and the group chat keeps going " * 5

    [plan] = _plans(await _lore({"message": message, "include_source_lines": True}))

    assert plan["total"] == 2
    assert plan["source_lines"] == [[1, 2], [4, 5]]


async def test_the_photo_endpoint_passes_the_flag_through(monkeypatch):
    seen: dict = {}

    async def fake_handle_image_stream(*args, **kwargs):
        from fastapi.responses import PlainTextResponse

        seen.update(kwargs)
        return PlainTextResponse("ok")

    monkeypatch.setattr("routers.lore.handle_image_stream", fake_handle_image_stream)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        on = await client.post(
            "/lore/image/", files={"images": ("a.png", buf.getvalue(), "image/png")},
            data={"include_source_lines": "true"},
        )
        on_value = seen.get("include_source_lines")
        off = await client.post("/lore/image/", files={"images": ("a.png", buf.getvalue(), "image/png")})

    assert on.status_code == off.status_code == 200
    assert on_value is True
    assert seen["include_source_lines"] is False
