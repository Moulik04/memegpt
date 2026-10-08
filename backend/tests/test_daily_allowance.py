"""
A visitor's daily allowance, and whose address a limit is counted against.

Covered here, bottom to top:
  - visitor.py: an address is believed only when the frontend's server
    vouches for it with the shared secret, directly or through a signed
    token. Anything a direct caller can type is ignored;
  - daily_quota.py: 10 memes per browser and 30 per network over a rolling
    24 hours, counted in memes, reserved up front and handed back when a
    meme is not made. A network is one IPv4 address or one IPv6 /64;
  - the routes: a visitor with nothing left costs no model call, one asking
    for more than is left gets what is left and is told, and each of the
    three "can't make that right now" cases says its own thing.

No network call: the model, moderation and rendering are stubbed.
"""

from __future__ import annotations

import io
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from starlette.requests import Request

import daily_quota
import routers.generate as generate_router
import visitor as visitor_module
from config import Settings
from main import app
from nlp import intent_router
from nlp.text_moderation import ModerationResult
from schemas import IntentResponse
from storage import SavedMeme
from uploads.safe_ingest import CleanImage
from visitor import (
    PROXY_ADDRESS_HEADER,
    PROXY_SECRET_HEADER,
    VISIT_TOKEN_HEADER,
    Visitor,
    identify,
    network_of,
    rate_limit_key,
    sign_visit,
)

_SECRET = "shared-between-frontend-and-backend"
_YOURS = "That's your 2 memes for today. They refill over the next 24 hours."
_NETWORK = "Everyone on your network has used today's 3 memes. They refill over the next 24 hours."
_DAILY = (
    "MemeGPT runs on a free daily AI budget, and today's is used up. "
    "It refills gradually, so try again in a few hours."
)
_BUSY = "MemeGPT is busy, try again in a minute."


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def limits(monkeypatch):
    """Sets the limits both modules read. Call it with what a test needs."""

    def apply(*, browser: int = 2, address: int = 3, secret: str = _SECRET) -> None:
        settings = _settings(
            daily_memes_per_browser=browser, daily_memes_per_address=address, proxy_shared_secret=secret
        )
        monkeypatch.setattr(daily_quota, "get_settings", lambda: settings)
        monkeypatch.setattr(visitor_module, "get_settings", lambda: settings)

    return apply


def _request(headers: dict[str, str] | None = None, client: str = "10.0.0.7") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": (client, 51234)})


# --- whose address ----------------------------------------------------------


def test_an_address_header_alone_is_ignored(limits):
    """What a direct caller would try first."""
    limits()

    seen = identify(_request({PROXY_ADDRESS_HEADER: "203.0.113.9"}))

    assert seen.address == "10.0.0.7"
    assert seen.address_verified is False


def test_the_frontends_server_is_believed_with_the_secret(limits):
    limits()

    seen = identify(_request({PROXY_SECRET_HEADER: _SECRET, PROXY_ADDRESS_HEADER: "203.0.113.9"}))

    assert seen.address == "203.0.113.9"
    assert seen.address_verified is True


def test_a_wrong_secret_is_the_same_as_none(limits):
    limits()

    seen = identify(_request({PROXY_SECRET_HEADER: "a guess", PROXY_ADDRESS_HEADER: "203.0.113.9"}))

    assert seen.address == "10.0.0.7"
    assert seen.address_verified is False


def test_with_no_secret_configured_nothing_is_believed(limits):
    """An empty secret must not match an empty header."""
    limits(secret="")

    seen = identify(_request({PROXY_SECRET_HEADER: "", PROXY_ADDRESS_HEADER: "203.0.113.9"}))

    assert seen.address == "10.0.0.7"
    assert seen.address_verified is False


def test_a_signed_token_carries_the_address_for_a_direct_upload(limits):
    limits()
    token = sign_visit("203.0.113.9", int(time.time()) + 600, _SECRET)

    seen = identify(_request({VISIT_TOKEN_HEADER: token}))

    assert seen.address == "203.0.113.9"
    assert seen.address_verified is True


def test_an_ipv6_address_survives_the_token(limits):
    limits()
    token = sign_visit("2001:db8::1", int(time.time()) + 600, _SECRET)

    assert identify(_request({VISIT_TOKEN_HEADER: token})).address == "2001:db8::1"


@pytest.mark.parametrize(
    "address,issued_by_the_frontend",
    [
        ("203.0.113.9", "v1.4102444800.MjAzLjAuMTEzLjk.caf3875bd1427013bcbd82138df651b1a4df5abc22f7e2ac6533f4e89085259f"),
        ("2001:db8::1", "v1.4102444800.MjAwMTpkYjg6OjE.0824d102b8ea4a96144953ad9dbd7978913c1b86a54aba5acb3d8b436ea94b51"),
    ],
)
def test_tokens_from_the_frontends_code_are_accepted(limits, address, issued_by_the_frontend):
    """These two were produced by the same Node calls app/api/visit/route.ts
    makes (secret "test-secret", expiry in 2100). The route and visitor.py
    are written in different languages and have to agree on every byte."""
    limits(secret="test-secret")

    assert sign_visit(address, 4102444800, "test-secret") == issued_by_the_frontend
    assert identify(_request({VISIT_TOKEN_HEADER: issued_by_the_frontend})).address == address


def _swap_address(token: str, address: str) -> str:
    version, expires, _, signature = token.split(".")
    encoded = sign_visit(address, int(expires), "whatever").split(".")[2]
    return ".".join([version, expires, encoded, signature])


def _token_cases() -> list[tuple[str, str]]:
    now = int(time.time())
    good = sign_visit("203.0.113.9", now + 600, _SECRET)
    return [
        ("expired", sign_visit("203.0.113.9", now - 1, _SECRET)),
        ("signed with another secret", sign_visit("203.0.113.9", now + 600, "not the secret")),
        ("address changed after signing", _swap_address(good, "198.51.100.1")),
        ("expiry changed after signing", good.replace(str(now + 600), str(now + 99999))),
        ("garbage", "v1.not-a-token"),
        ("empty parts", "v1..."),
    ]


@pytest.mark.parametrize("why,token", _token_cases(), ids=[c[0] for c in _token_cases()])
def test_a_token_that_does_not_check_out_is_ignored(limits, why, token):
    limits()

    seen = identify(_request({VISIT_TOKEN_HEADER: token}))

    assert seen.address == "10.0.0.7"
    assert seen.address_verified is False


def test_per_minute_limits_are_keyed_on_the_believed_address(limits):
    limits()

    via_frontend = _request({PROXY_SECRET_HEADER: _SECRET, PROXY_ADDRESS_HEADER: "203.0.113.9"})
    forged = _request({PROXY_ADDRESS_HEADER: "203.0.113.9"})

    assert rate_limit_key(via_frontend) == "203.0.113.9"
    assert rate_limit_key(forged) == "10.0.0.7"


# --- the allowance ----------------------------------------------------------


def _visitor(browser: str | None = "browser-a", address: str = "203.0.113.9") -> Visitor:
    return Visitor(address=address, address_verified=True, browser=browser)


def test_a_browser_gets_its_allowance_and_no_more(limits):
    limits(browser=2, address=30)

    assert daily_quota.reserve(_visitor(), 1).granted == 1
    assert daily_quota.reserve(_visitor(), 1).granted == 1
    refused = daily_quota.reserve(_visitor(), 1)

    assert refused.granted == 0
    assert refused.ran_out()
    assert refused.allowance_now().limited_by == daily_quota.LIMITED_BY_BROWSER


def test_asking_for_more_than_is_left_grants_what_is_left(limits):
    limits(browser=10, address=30)
    daily_quota.reserve(_visitor(), 8)

    reservation = daily_quota.reserve(_visitor(), 5)

    assert reservation.granted == 2
    assert daily_quota.allowance(_visitor()).remaining == 0


def test_memes_that_were_not_made_are_handed_back(limits):
    limits(browser=10, address=30)

    reservation = daily_quota.reserve(_visitor(), 5)
    reservation.settle(made=2)
    reservation.settle(made=2)  # settling twice must not hand back twice

    assert daily_quota.allowance(_visitor()).remaining == 8
    assert daily_quota.allowance(_visitor(browser="browser-b")).remaining == 10


def test_a_new_browser_id_is_a_new_allowance_up_to_the_address_ceiling(limits):
    """Clearing cookies gets a fresh browser's worth, on the same address."""
    limits(browser=2, address=3)

    assert daily_quota.reserve(_visitor("first"), 2).granted == 2
    second = daily_quota.reserve(_visitor("second"), 2)

    assert second.granted == 1
    assert second.allowance_now().limited_by == daily_quota.LIMITED_BY_ADDRESS
    assert daily_quota.reserve(_visitor("third"), 1).granted == 0


def test_another_address_is_not_affected(limits):
    limits(browser=2, address=3)
    daily_quota.reserve(_visitor("first"), 2)
    daily_quota.reserve(_visitor("second"), 2)

    assert daily_quota.reserve(_visitor("third", address="198.51.100.1"), 2).granted == 2


@pytest.mark.parametrize(
    "address,network",
    [
        ("203.0.113.9", "203.0.113.9"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:DB8:0001:0002:0000:0000:0000:0001", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("fe80::1%en0", "fe80::/64"),
        ("::ffff:203.0.113.9", "203.0.113.9"),
        ("unknown", "unknown"),
        ("testclient", "testclient"),
    ],
)
def test_a_network_is_an_ipv4_address_or_an_ipv6_64(address, network):
    assert network_of(address) == network


def test_ipv6_addresses_in_one_64_share_the_ceiling(limits):
    """One device can give itself a new address inside its /64 whenever it
    likes, so each of those must not be a fresh ceiling."""
    limits(browser=2, address=3)

    assert daily_quota.reserve(_visitor("first", address="2001:db8:1:2::1"), 2).granted == 2
    second = daily_quota.reserve(_visitor("second", address="2001:db8:1:2:aaaa:bbbb:cccc:dddd"), 2)

    assert second.granted == 1
    assert second.allowance_now().limited_by == daily_quota.LIMITED_BY_ADDRESS
    assert daily_quota.reserve(_visitor("third", address="2001:db8:1:2:1234::9"), 1).granted == 0


def test_the_next_64_is_another_network(limits):
    limits(browser=2, address=3)
    daily_quota.reserve(_visitor("first", address="2001:db8:1:2::1"), 2)
    daily_quota.reserve(_visitor("second", address="2001:db8:1:2::2"), 2)

    assert daily_quota.reserve(_visitor("third", address="2001:db8:1:3::1"), 2).granted == 2


def test_neighbouring_ipv4_addresses_are_not_grouped(limits):
    limits(browser=2, address=3)
    daily_quota.reserve(_visitor("first", address="203.0.113.9"), 2)
    daily_quota.reserve(_visitor("second", address="203.0.113.9"), 2)

    assert daily_quota.reserve(_visitor("third", address="203.0.113.10"), 2).granted == 2


def test_an_ipv4_address_written_as_ipv6_is_the_same_network(limits):
    limits(browser=2, address=3)
    daily_quota.reserve(_visitor("first", address="203.0.113.9"), 2)

    assert daily_quota.reserve(_visitor("second", address="::ffff:203.0.113.9"), 2).granted == 1


def test_handing_back_reaches_the_shared_64(limits):
    limits(browser=5, address=5)

    reservation = daily_quota.reserve(_visitor("first", address="2001:db8:1:2::1"), 5)
    reservation.settle(made=1)

    assert daily_quota.allowance(_visitor("second", address="2001:db8:1:2::2")).remaining == 4


def test_leaving_the_browser_id_off_is_not_worth_more(limits):
    limits(browser=2, address=30)

    assert daily_quota.reserve(_visitor(browser=None), 2).granted == 2
    assert daily_quota.reserve(_visitor(browser=None), 1).granted == 0


def test_the_address_ceiling_is_off_without_a_secret(limits):
    """Without it the address is the frontend's server for everyone, and one
    ceiling would be shared by the whole site."""
    limits(browser=2, address=3, secret="")

    assert daily_quota.reserve(_visitor("first"), 2).granted == 2
    assert daily_quota.reserve(_visitor("second"), 2).granted == 2


def test_the_allowance_comes_back_after_24_hours(limits, monkeypatch):
    limits(browser=2, address=30)
    now = [1_000_000.0]
    monkeypatch.setattr(daily_quota.time, "time", lambda: now[0])
    daily_quota.reserve(_visitor(), 1)
    now[0] += 12 * 3600
    daily_quota.reserve(_visitor(), 1)

    now[0] += 12 * 3600 + 1
    assert daily_quota.allowance(_visitor()).remaining == 1

    now[0] += 12 * 3600
    assert daily_quota.allowance(_visitor()).remaining == 2


def test_zero_switches_a_limit_off(limits):
    limits(browser=0, address=0)

    assert daily_quota.allowance(_visitor()).remaining is None
    assert daily_quota.reserve(_visitor(), 50).granted == 50


# --- the routes -------------------------------------------------------------


def _events(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in raw_text.splitlines() if line.startswith("data: ")]


def _notices(events: list[dict]) -> list[tuple[str | None, str]]:
    return [(e.get("reason"), e["message"]) for e in events if e["type"] == "error"]


def _memes(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "done" and e["message"].get("meme_url")]


@pytest.fixture
def picks(monkeypatch) -> list[str]:
    """A router that always picks, and a renderer that writes nothing.
    Returns the messages the router was asked about."""
    asked: list[str] = []

    async def fake_parse_intent(user_message, **kwargs) -> IntentResponse:
        asked.append(user_message)
        return IntentResponse(template_id="drake", texts={"rejected_option": "a"}, reasoning="a pick")

    async def fake_compose_meme(template_id, texts, **kwargs) -> SavedMeme:
        n = len(asked)
        return SavedMeme(meme_id=f"meme-{n}", url=f"/static/generated/meme-{n}.png", path=None)

    monkeypatch.setattr("routers.chat.parse_intent", fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", fake_compose_meme)
    monkeypatch.setattr(generate_router, "compose_meme", fake_compose_meme)
    return asked


_HEADERS = {"X-MemeGPT-User": "browser-a"}


async def _post(path: str, body: dict, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers or _HEADERS)


async def test_chat_stops_at_the_allowance_without_calling_the_model(limits, picks):
    limits(browser=2, address=30)
    for _ in range(2):
        assert len(_memes(_events((await _post("/chat/", {"message": "monday again"})).text))) == 1

    events = _events((await _post("/chat/", {"message": "monday again"})).text)

    assert _notices(events) == [("visitor_limit", _YOURS)]
    assert _memes(events) == []
    assert len(picks) == 2
    assert events[-1] == {"type": "batch_done", "total": 0, "succeeded": 0}


async def test_another_browser_is_not_affected(limits, picks):
    limits(browser=1, address=30)
    await _post("/chat/", {"message": "monday again"})

    events = _events((await _post("/chat/", {"message": "monday again"}, {"X-MemeGPT-User": "browser-b"})).text)

    assert len(_memes(events)) == 1


async def test_lore_asking_for_more_than_is_left_makes_what_is_left_and_says_so(limits, picks, monkeypatch):
    """A 5-count Lore is 5 memes. With 2 left it is split into 2, not into 5
    with 3 thrown away."""
    limits(browser=2, address=30)
    prompts: list[str] = []

    async def segmenter(client, settings, messages, temperature=0.75, max_tokens=None):
        prompts.append(messages[0]["content"])
        return json.dumps({"contexts": [
            {"situation": "the landlord raised the rent again"},
            {"situation": "my flight got cancelled at the gate"},
        ]})

    monkeypatch.setattr("nlp.segmentation.call_llm", segmenter)

    events = _events((await _post("/lore/", {"message": "a long paste", "meme_count": 5})).text)

    assert "The user asked for 2 memes" in prompts[0]
    assert len(_memes(events)) == 2
    assert _notices(events) == [("visitor_limit", _YOURS)]
    assert events[-1] == {"type": "batch_done", "total": 2, "succeeded": 2}
    assert daily_quota.allowance(_visitor()).remaining == 0


async def test_a_meme_that_was_not_made_does_not_count(limits, monkeypatch):
    limits(browser=2, address=30)

    async def broken_parse_intent(user_message, **kwargs):
        raise RuntimeError("no pick")

    monkeypatch.setattr("routers.chat.parse_intent", broken_parse_intent)

    events = _events((await _post("/chat/", {"message": "monday again"})).text)

    assert _memes(events) == []
    assert daily_quota.allowance(_visitor(address="127.0.0.1")).remaining == 2


async def test_the_site_budget_notice_does_not_count(limits, monkeypatch):
    """Nothing was made, and the pre-made meme shown with it is not theirs."""
    limits(browser=2, address=30)

    async def out_of_budget(user_message, **kwargs) -> IntentResponse:
        return IntentResponse(
            template_id="hide_the_pain_harold",
            texts={"top_text": "x"},
            reasoning=intent_router.DAILY_BUDGET_FALLBACK_REASONING,
        )

    monkeypatch.setattr("routers.chat.parse_intent", out_of_budget)

    events = _events((await _post("/chat/", {"message": "monday again"})).text)

    assert _notices(events) == [("site_budget", _DAILY)]
    assert daily_quota.allowance(_visitor(address="127.0.0.1")).remaining == 2


async def test_the_network_ceiling_says_whose_allowance_ran_out(limits, picks):
    """Someone opening the app for the first time on a busy network has made
    no memes, so the wording must not say the memes were theirs."""
    limits(browser=2, address=3)
    via_frontend = {PROXY_SECRET_HEADER: _SECRET, PROXY_ADDRESS_HEADER: "203.0.113.9"}
    for browser in ("first", "first", "second"):
        await _post("/chat/", {"message": "monday again"}, {"X-MemeGPT-User": browser, **via_frontend})

    events = _events(
        (await _post("/chat/", {"message": "monday again"}, {"X-MemeGPT-User": "third", **via_frontend})).text
    )

    assert _notices(events) == [("visitor_limit", _NETWORK)]
    assert len(picks) == 3


async def test_rotating_through_a_64_does_not_dodge_the_ceiling(limits, picks):
    """A new address and a new browser id on every request, all inside one
    /64: the fourth is refused without a model call."""
    limits(browser=2, address=3)

    def rotated(n: int) -> dict:
        return {
            "X-MemeGPT-User": f"browser-{n}",
            PROXY_SECRET_HEADER: _SECRET,
            PROXY_ADDRESS_HEADER: f"2001:db8:1:2::{n + 1:x}",
        }

    for n in range(3):
        assert len(_memes(_events((await _post("/chat/", {"message": "monday again"}, rotated(n))).text))) == 1

    events = _events((await _post("/chat/", {"message": "monday again"}, rotated(3))).text)

    assert _notices(events) == [("visitor_limit", _NETWORK)]
    assert len(picks) == 3


async def test_a_direct_caller_cannot_borrow_someone_elses_address(limits, picks):
    """The forged header is ignored, so these all count against the one
    connection they really came from."""
    limits(browser=2, address=3)
    for n in range(3):
        await _post(
            "/chat/", {"message": "monday again"},
            {"X-MemeGPT-User": f"made-up-{n}", PROXY_ADDRESS_HEADER: f"203.0.113.{n}"},
        )

    events = _events(
        (await _post(
            "/chat/", {"message": "monday again"},
            {"X-MemeGPT-User": "made-up-3", PROXY_ADDRESS_HEADER: "203.0.113.3"},
        )).text
    )

    assert _notices(events) == [("visitor_limit", _NETWORK)]
    assert len(picks) == 3


# --- photos ------------------------------------------------------------------


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


async def _post_images(count: int, **form_fields) -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/chat/image/",
            files=[("images", (f"photo{i}.jpg", _jpeg(), "image/jpeg")) for i in range(count)],
            data={k: str(v) for k, v in form_fields.items()},
            headers=_HEADERS,
        )
    assert resp.status_code == 200
    return _events(resp.text)


async def test_a_photo_is_not_looked_at_when_nothing_is_left(limits, monkeypatch):
    """Every photo costs model tokens whether or not a meme comes of it."""
    limits(browser=1, address=30)
    daily_quota.reserve(_visitor(address="127.0.0.1"), 1)

    async def must_not_ingest(upload):
        raise AssertionError("no photo call for a visitor with nothing left")

    monkeypatch.setattr("routers.chat.safe_ingest", must_not_ingest)

    events = await _post_images(1)

    assert _notices(events) == [
        ("visitor_limit", "That's your 1 memes for today. They refill over the next 24 hours.")
    ]


async def test_canvas_captions_only_the_photos_the_allowance_covers(limits, monkeypatch):
    limits(browser=2, address=30)
    captioned: list[int] = []

    async def clean(upload):
        return CleanImage(
            image=Image.new("RGB", (10, 10)), width=10, height=10,
            content_type="image/jpeg", source_filename=upload.filename,
        )

    async def captions(image, user_text=None):
        captioned.append(1)
        return {"top_text": f"top {len(captioned)}", "bottom_text": "bottom"}

    async def fake_compose_on_image(image, texts) -> SavedMeme:
        return SavedMeme(meme_id="canvas", url="/static/generated/canvas.png", path=None)

    monkeypatch.setattr("routers.chat.safe_ingest", clean)
    monkeypatch.setattr("routers.chat.generate_canvas_captions", captions)
    monkeypatch.setattr("routers.chat.compose_meme_on_image", fake_compose_on_image)

    events = await _post_images(3, message="make this a meme")

    assert len(captioned) == 2
    assert len(_memes(events)) == 2
    assert _notices(events) == [("visitor_limit", _YOURS)]


# --- Make --------------------------------------------------------------------

_MAKE_BODY = {"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}}


@pytest.fixture
def captions_pass(monkeypatch):
    async def passes(text):
        return ModerationResult(passed=True)

    monkeypatch.setattr(generate_router, "moderate_text", passes)


async def test_make_counts_toward_the_same_allowance(limits, picks, captions_pass):
    limits(browser=2, address=30)
    for _ in range(2):
        assert (await _post("/generate/", _MAKE_BODY)).status_code == 200

    resp = await _post("/generate/", _MAKE_BODY)

    assert resp.status_code == 429
    assert resp.json() == {"detail": _YOURS, "reason": "visitor_limit"}


async def test_a_refused_caption_does_not_count(limits, picks, monkeypatch):
    limits(browser=2, address=30)

    async def refuses(text):
        return ModerationResult(passed=False, category="hate")

    monkeypatch.setattr(generate_router, "moderate_text", refuses)

    assert (await _post("/generate/", _MAKE_BODY)).status_code == 400
    assert daily_quota.allowance(_visitor(address="127.0.0.1")).remaining == 2


async def test_this_apps_own_per_minute_limit_says_busy(limits, picks, captions_pass):
    limits(browser=0, address=0)
    statuses = [(await _post("/generate/", _MAKE_BODY)).status_code for _ in range(20)]

    resp = await _post("/generate/", _MAKE_BODY)

    assert statuses == [200] * 20
    assert resp.status_code == 429
    assert resp.json()["detail"] == _BUSY
    assert resp.json()["reason"] == "busy"
