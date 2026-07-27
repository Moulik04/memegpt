"""
Phase 0 safety-gate tests — required before Phase 1 may start, per
memegpt-multimodal-master-prompt.md: oversized file rejected; a renamed
.exe -> .jpg rejected by magic-byte check; EXIF GPS provably absent from
output bytes; decompression bomb rejected; moderation-failure path returns
a refusal and leaves zero temp files behind.
"""

from __future__ import annotations

import pytest

from storage import OUTPUT_DIR
from uploads.moderation import ModerationResult
from uploads.safe_ingest import ModerationRejected, UploadRejected, safe_ingest


async def _fake_moderation_pass(image):
    return ModerationResult(passed=True)


async def _fake_moderation_fail(image):
    return ModerationResult(passed=False, category="test_category")


@pytest.fixture(autouse=True)
def _default_moderation_passes(monkeypatch):
    """Every test in this file gets a passing moderation stub by default —
    the moderation-specific tests below override it explicitly. This keeps
    the size/type/dimension/EXIF tests independent of network access or a
    configured GROQ_API_KEY."""
    monkeypatch.setattr("uploads.safe_ingest.moderate_image", _fake_moderation_pass)


async def test_oversized_file_rejected(oversized_upload):
    with pytest.raises(UploadRejected) as exc_info:
        await safe_ingest(oversized_upload)
    assert exc_info.value.reason == "file_too_large"


async def test_fake_exe_rejected_by_magic_bytes(fake_exe_upload):
    with pytest.raises(UploadRejected) as exc_info:
        await safe_ingest(fake_exe_upload)
    assert exc_info.value.reason == "unrecognized_file_type"


async def test_oversized_dimension_rejected(oversized_dimension_upload):
    with pytest.raises(UploadRejected) as exc_info:
        await safe_ingest(oversized_dimension_upload)
    assert exc_info.value.reason == "dimensions_too_large"


async def test_exif_gps_stripped(exif_gps_jpeg_upload):
    clean = await safe_ingest(exif_gps_jpeg_upload)
    # The source fixture has both a GPS IFD and a Model tag — assert the
    # output image carries NO exif data at all, not just no GPS specifically.
    assert dict(clean.image.getexif()) == {}


async def test_happy_path_returns_clean_image(tiny_jpeg_upload):
    clean = await safe_ingest(tiny_jpeg_upload)
    assert clean.width == 10
    assert clean.height == 10
    assert clean.content_type == "image/jpeg"


async def test_moderation_rejected_generic_and_no_temp_files(tiny_jpeg_upload, monkeypatch):
    monkeypatch.setattr("uploads.safe_ingest.moderate_image", _fake_moderation_fail)

    before = set(OUTPUT_DIR.glob("*"))

    with pytest.raises(ModerationRejected) as exc_info:
        await safe_ingest(tiny_jpeg_upload)
    assert exc_info.value.category == "test_category"

    after = set(OUTPUT_DIR.glob("*"))
    assert after == before, "safe_ingest must never write files to disk, even on rejection"
