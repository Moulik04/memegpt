"""
What the app really stores and what its two erase actions really remove,
run against a real Postgres and a real S3 API instead of fakes.

Opt-in: skipped unless `pgserver` (a pip-installable Postgres) and `moto`
(an S3 mock) are importable, so the default suite and CI need nothing new.

    pip install pgserver moto
    pytest tests/test_data_lifecycle.py

Why this exists alongside test_db.py and test_forget_me.py: those check the
SQL text and the call order with a fake pool, and a fake pool cannot refuse
a delete. "Forget me" once failed on a foreign key for every signed-in user
with saved history, returned a 500 the page ignored, and removed nothing,
while every one of those tests passed. Only a database that enforces its
constraints can catch that, and only an object store that holds real
objects can show whether a meme's image is gone.

Sign-in verification, the model and the image safety check are stubbed.
Everything under test is real: routes, SQL, constraints, storage calls.
"""

from __future__ import annotations

import io
import json

import pytest

pgserver = pytest.importorskip("pgserver")
moto = pytest.importorskip("moto")

import asyncpg  # noqa: E402
import boto3  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from PIL import Image  # noqa: E402

import db  # noqa: E402
import db.pool  # noqa: E402
import storage  # noqa: E402
from auth import VerifiedUser  # noqa: E402
from config import get_settings  # noqa: E402
from main import app  # noqa: E402
from rate_limit import limiter  # noqa: E402
from schemas import IntentResponse, VisionDescription  # noqa: E402
from uploads.moderation import ModerationResult  # noqa: E402

BUCKET = "memes-test"
ALICE, BOB = "user-alice", "user-bob"
ALICE_BROWSER, BOB_BROWSER, VISITOR_BROWSER = "anon-alice", "anon-bob", "anon-visitor"
PASTE = "PASTE-MARKER the mail room key went missing again and sam will not hand it over. " * 6


@pytest.fixture(scope="module")
def postgres_dsn(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("postgres"), cleanup_mode="stop")
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
async def world(postgres_dsn, monkeypatch, tmp_path):
    """A clean database and bucket, the app pointed at both, and outside
    services stubbed. Yields helpers for acting as a user and for looking at
    what is actually there afterwards."""
    conn = await asyncpg.connect(postgres_dsn)
    await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

    # The bundled Postgres ships without pgcrypto. The schema asks for it only
    # to get gen_random_uuid(), which Postgres 13+ has built in.
    schema = db.pool._SCHEMA_PATH.read_text()
    local_schema = tmp_path / "schema.sql"
    local_schema.write_text(schema.replace("CREATE EXTENSION IF NOT EXISTS pgcrypto;", ""))
    monkeypatch.setattr(db.pool, "_SCHEMA_PATH", local_schema)

    for name, value in {
        "DATABASE_URL": postgres_dsn,
        "R2_ACCOUNT_ID": "local", "R2_ACCESS_KEY_ID": "test", "R2_SECRET_ACCESS_KEY": "test",
        "R2_BUCKET": BUCKET, "R2_PUBLIC_BASE_URL": f"https://memes.test/{BUCKET}",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    await db.pool.close_pool()
    monkeypatch.setattr(limiter, "enabled", False)

    async def fake_user(request):
        token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not token or token == "does-not-verify":
            return None
        return VerifiedUser(user_id=token, email=None)

    async def fake_parse_intent(user_message, **kwargs):
        return IntentResponse(template_id="hide_the_pain_harold",
                              texts={"top_text": "a caption", "bottom_text": "another"}, reasoning="stub")

    async def fake_moderate_image(image):
        return ModerationResult(passed=True)

    async def fake_describe_image(image, user_text=None):
        return VisionDescription(situation="a description of the photo")

    for module in ("routers.chat", "routers.conversations", "routers.feedback", "routers.me"):
        monkeypatch.setattr(f"{module}.get_verified_user", fake_user)
    monkeypatch.setattr("routers.chat.parse_intent", fake_parse_intent)
    monkeypatch.setattr("routers.chat.describe_image", fake_describe_image)
    monkeypatch.setattr("uploads.safe_ingest.moderate_image", fake_moderate_image)

    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
        s3.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(storage, "_cached_r2_client", lambda *args: s3)

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            yield _World(client, conn, s3)

    await db.pool.close_pool()
    await conn.close()
    get_settings.cache_clear()


class _World:
    def __init__(self, client, conn, s3):
        self.client, self.conn, self.s3 = client, conn, s3

    @staticmethod
    def headers(browser: str | None, user: str | None = None) -> dict:
        h = {"X-MemeGPT-User": browser} if browser else {}
        if user:
            h["Authorization"] = f"Bearer {user}"
        return h

    async def chat(self, message: str, browser: str, user: str | None = None) -> list[str]:
        """Sends one Chat message (into a new saved conversation when signed
        in) and returns the ids of the memes it produced."""
        body: dict = {"message": message}
        if user:
            created = await self.client.post("/conversations", json={"surface": "chat"},
                                             headers=self.headers(browser, user))
            body["conversation_row_id"] = created.json()["id"]
        resp = await self.client.post("/chat/", json=body, headers=self.headers(browser, user))
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        memes = [e["message"]["meme_id"] for e in events if e.get("type") == "done"]
        # Every test below is about what happens to these memes afterwards. A
        # request that quietly produced none would let them all pass on nothing.
        assert memes, f"no meme was generated: {resp.status_code} {resp.text[:300]}"
        return memes

    async def forget(self, browser: str | None, user: str | None = None):
        return await self.client.request("DELETE", "/me", headers=self.headers(browser, user))

    def images(self) -> set[str]:
        listed = self.s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])
        return {obj["Key"].split(".")[0] for obj in listed}

    async def rows(self, user: str | None, browser: str | None) -> dict[str, int]:
        c = self.conn
        return {
            "memes": await c.fetchval("SELECT count(*) FROM memes WHERE user_id=$1 OR anon_user_id=$2", user, browser),
            "feedback": await c.fetchval("SELECT count(*) FROM feedback WHERE user_id=$1 OR anon_user_id=$2", user, browser),
            "conversations": await c.fetchval("SELECT count(*) FROM conversations WHERE user_id=$1", user),
            "messages": await c.fetchval(
                "SELECT count(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=$1", user),
            "lexicon": await c.fetchval("SELECT count(*) FROM lore_lexicon WHERE user_id=$1 OR anon_user_id=$2", user, browser),
        }


_NOTHING = {"memes": 0, "feedback": 0, "conversations": 0, "messages": 0, "lexicon": 0}


async def _thumbs_up(world: _World, meme_id: str, browser: str, user: str | None = None) -> None:
    await world.client.post("/feedback/", json={"template_id": "hide_the_pain_harold", "rating": "up",
                                                "meme_id": meme_id, "texts": {}},
                            headers=world.headers(browser, user))


# --- what is stored ---------------------------------------------------------


async def test_signed_out_use_stores_the_meme_and_no_text(world):
    memes = await world.chat("VISITOR-MARKER my boss scheduled a meeting about the meeting", VISITOR_BROWSER)

    assert len(memes) == 1 and set(memes) <= world.images()
    assert await world.conn.fetchval("SELECT count(*) FROM conversations") == 0
    assert await world.conn.fetchval("SELECT count(*) FROM messages") == 0
    stored = await world.conn.fetchrow("SELECT * FROM memes WHERE id=$1", memes[0])
    assert "VISITOR-MARKER" not in json.dumps(dict(stored), default=str)


async def test_signed_in_chat_history_stores_the_message_text(world):
    await world.chat("ALICE-MARKER my boss scheduled a meeting about the meeting", ALICE_BROWSER, ALICE)

    contents = [r["content"] for r in await world.conn.fetch("SELECT content FROM messages")]
    assert contents and all("ALICE-MARKER" in c for c in contents)


async def test_an_uploaded_photo_leaves_only_the_meme_behind(world):
    photo = io.BytesIO()
    Image.new("RGB", (320, 240), (200, 120, 40)).save(photo, "JPEG")

    resp = await world.client.post("/chat/image/", files=[("images", ("p.jpg", photo.getvalue(), "image/jpeg"))],
                                   headers=world.headers(VISITOR_BROWSER))
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    memes = {e["message"]["meme_id"] for e in events if e.get("type") == "done"}

    assert len(memes) == 1
    assert world.images() == memes  # the generated meme, and no copy of the upload


# --- deleting a conversation ------------------------------------------------


async def test_deleting_a_conversation_removes_its_rows_and_its_images(world):
    kept = await world.chat("keep this one", ALICE_BROWSER, ALICE)
    doomed = await world.chat("delete this one", ALICE_BROWSER, ALICE)
    await _thumbs_up(world, doomed[0], ALICE_BROWSER, ALICE)
    conversation = await world.conn.fetchval(
        "SELECT conversation_id FROM messages WHERE meme_id=$1", doomed[0])

    resp = await world.client.delete(f"/conversations/{conversation}", headers=world.headers(ALICE_BROWSER, ALICE))

    assert resp.status_code == 200
    assert await world.conn.fetchval("SELECT count(*) FROM messages WHERE conversation_id=$1", conversation) == 0
    assert await world.conn.fetchval("SELECT count(*) FROM memes WHERE id=$1", doomed[0]) == 0
    assert await world.conn.fetchval("SELECT count(*) FROM feedback WHERE meme_id=$1", doomed[0]) == 0
    assert doomed[0] not in world.images()
    assert kept[0] in world.images()


async def test_nobody_else_can_delete_a_conversation_or_its_images(world):
    memes = await world.chat("alice's chat", ALICE_BROWSER, ALICE)
    conversation = await world.conn.fetchval("SELECT conversation_id FROM messages WHERE meme_id=$1", memes[0])

    resp = await world.client.delete(f"/conversations/{conversation}", headers=world.headers(BOB_BROWSER, BOB))

    assert resp.status_code == 404
    assert memes[0] in world.images()
    assert (await world.rows(ALICE, ALICE_BROWSER))["conversations"] == 1


# --- Forget me --------------------------------------------------------------


async def test_forget_me_signed_in_with_history_removes_everything_of_theirs(world):
    """The case that used to fail on a foreign key and remove nothing."""
    alice_memes = await world.chat("first", ALICE_BROWSER, ALICE)
    alice_memes += await world.chat("second", ALICE_BROWSER, ALICE)
    await _thumbs_up(world, alice_memes[0], ALICE_BROWSER, ALICE)
    bob_memes = await world.chat("bob's chat", BOB_BROWSER, BOB)
    await _thumbs_up(world, bob_memes[0], BOB_BROWSER, BOB)
    bob_before = await world.rows(BOB, BOB_BROWSER)

    resp = await world.forget(ALICE_BROWSER, ALICE)

    assert resp.status_code == 200
    assert await world.rows(ALICE, ALICE_BROWSER) == _NOTHING
    assert not set(alice_memes) & world.images()
    assert await world.rows(BOB, BOB_BROWSER) == bob_before
    assert set(bob_memes) <= world.images()
    assert (await world.forget(ALICE_BROWSER, ALICE)).status_code == 200  # nothing left is not an error


async def test_forget_me_signed_out_removes_the_rows_and_the_images(world):
    memes = await world.chat("a visitor's meme", VISITOR_BROWSER)

    resp = await world.forget(VISITOR_BROWSER)

    assert resp.status_code == 200
    assert await world.rows(None, VISITOR_BROWSER) == _NOTHING
    assert not set(memes) & world.images()


async def test_a_browser_id_alone_cannot_erase_an_account(world):
    """Signed out, the only thing the caller presents is a value stored in
    a browser. That reaches anonymous data, not an account's history."""
    memes = await world.chat("alice's saved chat", ALICE_BROWSER, ALICE)
    before = await world.rows(ALICE, ALICE_BROWSER)

    resp = await world.forget(ALICE_BROWSER)

    assert resp.status_code == 200
    assert await world.rows(ALICE, ALICE_BROWSER) == before
    assert set(memes) <= world.images()


async def test_forget_me_with_an_unverifiable_sign_in_removes_nothing(world):
    memes = await world.chat("alice's saved chat", ALICE_BROWSER, ALICE)
    before = await world.rows(ALICE, ALICE_BROWSER)

    resp = await world.forget(ALICE_BROWSER, "does-not-verify")

    assert resp.status_code == 401
    assert await world.rows(ALICE, ALICE_BROWSER) == before
    assert set(memes) <= world.images()


async def test_forget_me_fails_loudly_and_whole_when_storage_refuses_then_retries_clean(world, monkeypatch):
    memes = await world.chat("alice's saved chat", ALICE_BROWSER, ALICE)
    before = await world.rows(ALICE, ALICE_BROWSER)
    real_delete_objects = world.s3.delete_objects

    def refuse(**kwargs):
        return {"Errors": [{"Key": o["Key"], "Code": "AccessDenied"} for o in kwargs["Delete"]["Objects"]]}

    monkeypatch.setattr(world.s3, "delete_objects", refuse)
    failed = await world.forget(ALICE_BROWSER, ALICE)

    assert failed.status_code == 500
    assert await world.rows(ALICE, ALICE_BROWSER) == before  # the rows still say where the images are
    assert set(memes) <= world.images()

    monkeypatch.setattr(world.s3, "delete_objects", real_delete_objects)
    retried = await world.forget(ALICE_BROWSER, ALICE)

    assert retried.status_code == 200
    assert await world.rows(ALICE, ALICE_BROWSER) == _NOTHING
    assert not set(memes) & world.images()
