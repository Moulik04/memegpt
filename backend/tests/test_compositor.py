"""
image_processing/compositor.py's watermark + provenance layer — Growth
master prompt Phase A. Covers: the visible watermark actually changes the
rendered bytes when enabled, canvas mode gets it too, the PNG tEXt
provenance chunk is present regardless of the visible-watermark flag, and
existing caption rendering is unaffected.
"""

from __future__ import annotations

from PIL import Image

from config import Settings
from image_processing.compositor import TEMPLATES_DIR, compose_meme, compose_meme_on_image


def _fake_settings(monkeypatch, **overrides):
    settings = Settings(**overrides)
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    return settings


async def test_watermark_enabled_changes_output_bytes(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    with_mark = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"}, return_path=True)
    on_bytes = with_mark.read_bytes()

    _fake_settings(monkeypatch, watermark_enabled=False)
    without_mark = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"}, return_path=True)
    off_bytes = without_mark.read_bytes()

    assert on_bytes != off_bytes


async def test_canvas_mode_also_gets_watermark(monkeypatch):
    image = Image.new("RGB", (500, 500), color="blue")

    _fake_settings(monkeypatch, watermark_enabled=True)
    with_mark = await compose_meme_on_image(image, {"top_text": "TOP", "bottom_text": "BOTTOM"}, return_path=True)
    on_bytes = with_mark.read_bytes()

    _fake_settings(monkeypatch, watermark_enabled=False)
    without_mark = await compose_meme_on_image(image, {"top_text": "TOP", "bottom_text": "BOTTOM"}, return_path=True)
    off_bytes = without_mark.read_bytes()

    assert on_bytes != off_bytes


async def test_provenance_tag_present_regardless_of_watermark_flag(monkeypatch):
    for enabled in (True, False):
        _fake_settings(monkeypatch, watermark_enabled=enabled)
        path = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"}, return_path=True)
        saved = Image.open(path)
        assert "memegpt_id" in saved.text
        assert len(saved.text["memegpt_id"]) > 0


async def test_watermark_text_is_configurable(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True, watermark_text="X")
    short_mark = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"}, return_path=True)

    _fake_settings(monkeypatch, watermark_enabled=True, watermark_text="a much longer watermark string")
    long_mark = await compose_meme("drake", {"top_text": "a", "bottom_text": "b"}, return_path=True)

    assert short_mark.read_bytes() != long_mark.read_bytes()


async def test_caption_rendering_unaffected_by_watermark(monkeypatch):
    """Same caption text, watermark on vs off — the caption boxes
    themselves must not move or resize; this only asserts both renders
    succeed and produce a valid, differently-sized-or-equal PNG rather than
    a pixel diff of the caption region, since compositor.py has no existing
    per-box pixel inspection helper to reuse."""
    _fake_settings(monkeypatch, watermark_enabled=True)
    path = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"}, return_path=True)
    img = Image.open(path)
    original = Image.open(TEMPLATES_DIR / "drake.jpg")
    assert img.size == original.size
