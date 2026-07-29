"""
Shared fixtures for the Phase 0 safety-gate tests. Every fixture is
synthesized in-test via Pillow — no binary files are committed to the repo.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from PIL import Image

from config import Settings, get_settings
from rate_limit import limiter
from storage import OUTPUT_DIR
from vector_db import chroma_client, examples_store


def _upload(data: bytes, filename: str = "photo.jpg") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.fixture(autouse=True, scope="session")
def _isolate_settings_from_real_dot_env():
    """The growth spec requires the full suite to pass with zero new env
    vars — but this developer's own backend/.env has real DATABASE_URL/R2
    credentials configured for actual Phase B usage. Without this, every
    test that doesn't explicitly monkeypatch get_settings would silently
    pick up those real credentials (pydantic-settings reads env_file by
    default) and could write real test data to the real R2 bucket/Postgres
    database. Settings.model_config is a class attribute shared by every
    `from config import Settings`/`get_settings()` reference across the
    whole codebase (they all point at the one class object), so mutating
    it here — rather than monkeypatching each module's own bound
    get_settings name individually — reaches all of them at once."""
    original_env_file = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    yield
    Settings.model_config["env_file"] = original_env_file
    get_settings.cache_clear()


@pytest.fixture(autouse=True, scope="session")
def _isolate_chroma_from_real_local_data(tmp_path_factory):
    """Found empirically: with no isolation, tests share the real
    backend/data/chroma/ directory with local dev. _isolate_settings_from_
    real_dot_env above nulls GEMINI_API_KEY during tests, so a test that
    exercises the real (lazy, module-global-cached) _get_collection() path
    — e.g. test_intent_router.py's timeout test — creates/touches that
    real on-disk collection using ChromaDB's default *local* embedding
    function. Run the real dev server afterward (with GEMINI_API_KEY set)
    and get_or_create_collection() hard-crashes: ChromaDB refuses to open
    an existing collection whose persisted embedding-function config
    doesn't match the one just requested ("embedding function conflict:
    new: gemini_embedding_2 vs persisted: default"). Point both ChromaDB
    modules' _DB_PATH at a session-scoped temp dir instead, so the test
    suite never reads or writes the developer's real local ChromaDB data
    at all, in either direction."""
    # Both modules point at the same on-disk PersistentClient directory in
    # real usage too (meme_templates and meme_examples are two collections
    # within one client, not two separate directories) — mirror that here.
    tmp_dir = tmp_path_factory.mktemp("chroma_test_data")
    chroma_client._DB_PATH = tmp_dir
    examples_store._DB_PATH = tmp_dir
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """/chat/image/ is rate-limited (5/minute per client IP). Every test in
    this suite hits it from the same in-process ASGI transport, so without
    resetting between tests, later tests in a run get 429'd by earlier
    ones' request counts — reset the shared in-memory limiter state before
    each test rather than exhausting a real per-minute budget across a full
    test run."""
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _cleanup_generated_files():
    """Several tests exercise the real (unmocked) compose_meme()/
    compose_meme_on_image(), which write actual PNGs to
    backend/static/generated/ — clean up anything a test creates so repeated
    runs don't accumulate stray files in the repo."""
    before = set(OUTPUT_DIR.glob("*"))
    yield
    after = set(OUTPUT_DIR.glob("*"))
    for path in after - before:
        path.unlink(missing_ok=True)


@pytest.fixture
def tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def tiny_jpeg_upload(tiny_jpeg_bytes) -> UploadFile:
    return _upload(tiny_jpeg_bytes, "photo.jpg")


@pytest.fixture
def oversized_upload() -> UploadFile:
    """Larger than settings.max_image_bytes (10MB) — doesn't need to be a
    valid image, since the size cap must trip before any decode is attempted."""
    data = b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024)
    return _upload(data, "huge.jpg")


@pytest.fixture
def fake_exe_upload() -> UploadFile:
    """A PE-header stub renamed to .jpg — must be rejected by the magic-byte
    check regardless of the filename extension."""
    data = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 100
    return _upload(data, "totally_a_photo.jpg")


@pytest.fixture
def exif_gps_jpeg_upload() -> UploadFile:
    """A real JPEG with a fabricated EXIF GPS tag — Pillow can write EXIF
    natively (Image.Exif() + save(..., exif=...)), no extra dependency needed."""
    img = Image.new("RGB", (20, 20), color="green")
    exif = img.getexif()
    gps_ifd = exif.get_ifd(0x8825)  # GPSInfo IFD
    gps_ifd[1] = "N"                  # GPSLatitudeRef
    gps_ifd[2] = (40.0, 44.0, 54.0)   # GPSLatitude (deg, min, sec)
    exif[0x8825] = gps_ifd
    exif[0x0110] = "TestCameraModel"  # Model tag, as an extra metadata proxy
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return _upload(buf.getvalue(), "vacation.jpg")


@pytest.fixture
def oversized_dimension_upload() -> UploadFile:
    """8001x10 — cheap (80,010 pixels) but trips the explicit >8000px-per-side
    rule without needing an actual multi-hundred-MB decompression bomb."""
    buf = io.BytesIO()
    Image.new("RGB", (8001, 10), color="red").save(buf, format="PNG")
    return _upload(buf.getvalue(), "wide.png")
