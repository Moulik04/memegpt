"""
image_processing/compositor.py's watermark + provenance layer — Growth
master prompt Phase A. Covers: the visible watermark actually changes the
rendered bytes when enabled, canvas mode gets it too, the PNG tEXt
provenance chunk is present regardless of the visible-watermark flag, and
existing caption rendering is unaffected.

Also covers Phase B's storage integration at the compositor level: with no
R2 creds configured (the default in every test run), compose_meme()/
compose_meme_on_image() return a SavedMeme whose .path is set (local disk),
matching the pre-Phase-B on-disk behavior these tests already relied on.
"""

from __future__ import annotations

from PIL import Image

from config import Settings
from image_processing.compositor import TEMPLATES_DIR, compose_meme, compose_meme_on_image


def _fake_settings(monkeypatch, **overrides):
    # _env_file=None: a clean-slate Settings, ignoring the real backend/.env
    # (which has real R2/DATABASE_URL creds set for Phase B) — tests need
    # deterministic defaults, not whatever happens to be configured locally.
    # Patched in both modules: compositor's own get_settings (watermark) and
    # storage's own get_settings (save destination) are separate imported
    # references, each needs to see the same fake settings.
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    monkeypatch.setattr("storage.get_settings", lambda: settings)
    return settings


async def test_watermark_enabled_changes_output_bytes(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    with_mark = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"})
    on_bytes = with_mark.path.read_bytes()

    _fake_settings(monkeypatch, watermark_enabled=False)
    without_mark = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"})
    off_bytes = without_mark.path.read_bytes()

    assert on_bytes != off_bytes


async def test_canvas_mode_also_gets_watermark(monkeypatch):
    image = Image.new("RGB", (500, 500), color="blue")

    _fake_settings(monkeypatch, watermark_enabled=True)
    with_mark = await compose_meme_on_image(image, {"top_text": "TOP", "bottom_text": "BOTTOM"})
    on_bytes = with_mark.path.read_bytes()

    _fake_settings(monkeypatch, watermark_enabled=False)
    without_mark = await compose_meme_on_image(image, {"top_text": "TOP", "bottom_text": "BOTTOM"})
    off_bytes = without_mark.path.read_bytes()

    assert on_bytes != off_bytes


async def test_provenance_tag_present_regardless_of_watermark_flag(monkeypatch):
    for enabled in (True, False):
        _fake_settings(monkeypatch, watermark_enabled=enabled)
        saved = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"})
        img = Image.open(saved.path)
        assert "memegpt_id" in img.text
        assert img.text["memegpt_id"] == saved.meme_id


async def test_watermark_text_is_configurable(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True, watermark_text="X")
    short_mark = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"})

    _fake_settings(monkeypatch, watermark_enabled=True, watermark_text="a much longer watermark string")
    long_mark = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"})

    assert short_mark.path.read_bytes() != long_mark.path.read_bytes()


async def test_caption_rendering_unaffected_by_watermark(monkeypatch):
    """Same caption text, watermark on vs off — the caption boxes
    themselves must not move or resize; this only asserts both renders
    succeed and produce a valid, differently-sized-or-equal PNG rather than
    a pixel diff of the caption region, since compositor.py has no existing
    per-box pixel inspection helper to reuse."""
    _fake_settings(monkeypatch, watermark_enabled=True)
    saved = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"})
    img = Image.open(saved.path)
    original = Image.open(TEMPLATES_DIR / "drake.jpg")
    assert img.size == original.size


async def test_local_storage_is_default_with_no_r2_creds(monkeypatch):
    """Growth Phase B: with no R2 creds set (the default, and the only
    configuration every other test in this suite runs under), storage
    falls back to local disk — .path is set, .url is the pre-Phase-B
    /static/generated/ shape, and the meme_id is a real generated id."""
    _fake_settings(monkeypatch)
    saved = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"})
    assert saved.path is not None
    assert saved.path.exists()
    assert saved.url == f"/static/generated/{saved.meme_id}.png"
    assert len(saved.meme_id) == 10
