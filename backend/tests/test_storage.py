"""
storage/__init__.py — Growth Phase B's durable storage abstraction.
Covers: local-disk fallback (the default, zero-creds path every other test
in this suite runs under), the R2 path with a mocked boto3 client (never
hits real R2), meme_id format/unguessability, and the all-or-nothing R2
configuration gate.
"""

from __future__ import annotations

import string

from config import Settings
import storage


def _fake_settings(monkeypatch, **overrides):
    # _env_file=None: ignore the real backend/.env (which has real R2/
    # DATABASE_URL creds set for Phase B) — tests need deterministic
    # defaults, not whatever happens to be configured locally.
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    return settings


def test_generate_meme_id_is_base62_length_10():
    meme_id = storage.generate_meme_id()
    assert len(meme_id) == 10
    assert all(c in string.digits + string.ascii_letters for c in meme_id)


def test_generate_meme_id_is_not_constant():
    ids = {storage.generate_meme_id() for _ in range(50)}
    assert len(ids) == 50  # no collisions across 50 draws


async def test_local_storage_default_with_no_r2_creds(monkeypatch):
    _fake_settings(monkeypatch)
    saved = await storage.save_meme(b"fake png bytes")

    assert saved.path is not None
    assert saved.path.exists()
    assert saved.path.read_bytes() == b"fake png bytes"
    assert saved.url == f"/static/generated/{saved.meme_id}.png"
    saved.path.unlink()


async def test_local_storage_uses_provided_meme_id(monkeypatch):
    _fake_settings(monkeypatch)
    saved = await storage.save_meme(b"x", meme_id="fixedid1234")
    assert saved.meme_id == "fixedid1234"
    assert saved.path.name == "fixedid1234.png"
    saved.path.unlink()


def test_r2_not_configured_when_any_field_missing(monkeypatch):
    settings = Settings(
        r2_account_id="acct",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="bucket",
        r2_public_base_url="",  # missing this one field
    )
    assert storage._r2_configured(settings) is False


def test_r2_configured_when_all_fields_present():
    settings = Settings(
        r2_account_id="acct",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="bucket",
        r2_public_base_url="https://pub-xxx.r2.dev",
    )
    assert storage._r2_configured(settings) is True


async def test_r2_path_uploads_via_mocked_client_never_touches_disk(monkeypatch):
    """Never hits real R2 — the boto3 client is replaced with a fake that
    just records the call it received."""
    _fake_settings(
        monkeypatch,
        r2_account_id="acct",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="my-bucket",
        r2_public_base_url="https://pub-xxx.r2.dev",
    )

    calls = []

    class FakeR2Client:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(storage, "_r2_client", lambda settings: FakeR2Client())

    saved = await storage.save_meme(b"fake png bytes", meme_id="abc1234567")

    assert saved.path is None
    assert saved.url == "https://pub-xxx.r2.dev/abc1234567.png"
    assert len(calls) == 1
    assert calls[0]["Bucket"] == "my-bucket"
    assert calls[0]["Key"] == "abc1234567.png"
    assert calls[0]["Body"] == b"fake png bytes"
    assert calls[0]["ContentType"] == "image/png"


async def test_r2_public_base_url_trailing_slash_stripped(monkeypatch):
    _fake_settings(
        monkeypatch,
        r2_account_id="acct",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="my-bucket",
        r2_public_base_url="https://pub-xxx.r2.dev/",  # trailing slash
    )

    class FakeR2Client:
        def put_object(self, **kwargs):
            pass

    monkeypatch.setattr(storage, "_r2_client", lambda settings: FakeR2Client())

    saved = await storage.save_meme(b"x", meme_id="abc1234567")
    assert saved.url == "https://pub-xxx.r2.dev/abc1234567.png"
