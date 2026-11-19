"""
Every rendered meme is fully opaque: catalog templates (including the
transparent ones), canvas mode on the user's own photo, animated GIFs, and
the Arc card. Each test decodes the saved file, the same bytes a viewer
gets, rather than inspecting the in-memory image.
"""

from __future__ import annotations

from PIL import Image, ImageSequence

from config import Settings
from image_processing.compositor import (
    TEMPLATES_DIR,
    compose_arc_card,
    compose_meme,
    compose_meme_on_image,
)
from schemas import ArcStats, ArcTemplate


def _fake_settings(monkeypatch, **overrides):
    # Same clean-slate settings as test_compositor.py: no R2, local disk only.
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    monkeypatch.setattr("storage.get_settings", lambda: settings)
    return settings


def _assert_opaque(img: Image.Image) -> None:
    assert "transparency" not in img.info
    rgba = img.convert("RGBA")
    assert rgba.getchannel("A").getextrema() == (255, 255)


def _first_transparent_pixel(img: Image.Image) -> tuple[int, int]:
    alpha = img.convert("RGBA").getchannel("A")
    w, h = alpha.size
    for y in range(h):
        for x in range(w):
            if alpha.getpixel((x, y)) == 0:
                return x, y
    raise AssertionError("fixture has no transparent pixel")


async def test_static_meme_is_opaque_with_watermark(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    saved = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"})
    _assert_opaque(Image.open(saved.path))


async def test_transparent_template_is_flattened_onto_white(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    source = Image.open(TEMPLATES_DIR / "chill_guy.png")
    x, y = _first_transparent_pixel(source)

    saved = await compose_meme("chill_guy", {"top_text": "me", "bottom_text": "unbothered"})
    out = Image.open(saved.path)

    _assert_opaque(out)
    assert out.size == source.size
    assert out.convert("RGB").getpixel((x, y)) == (255, 255, 255)


async def test_animated_gif_template_is_flattened_onto_white(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    source = Image.open(TEMPLATES_DIR / "party_parrot.gif")
    x, y = _first_transparent_pixel(source)

    saved = await compose_meme("party_parrot", {"top_text": "friday", "bottom_text": "deploy"})
    out = Image.open(saved.path)

    assert out.n_frames > 1
    for frame in ImageSequence.Iterator(out):
        _assert_opaque(frame)
        # GIF re-quantizes colors, so near-white rather than exact.
        assert min(frame.convert("RGB").getpixel((x, y))) >= 240


async def test_gif_transparency_is_flattened_whatever_color_it_hides(monkeypatch, tmp_path):
    # party_parrot's transparent pixels happen to store white underneath, so
    # it renders white with or without flattening. This fixture hides black
    # there instead, the way plenty of GIFs do.
    from image_processing.template_configs import TemplateConfig, TextBoxConfig

    _fake_settings(monkeypatch, watermark_enabled=True)
    monkeypatch.setattr("image_processing.compositor.TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(
        "image_processing.compositor.get_config",
        lambda tid: TemplateConfig(
            template_id=tid,
            text_boxes=[TextBoxConfig("top_text", x_pct=5, y_pct=2, w_pct=90, h_pct=20, font_size_pct=7)],
            is_gif=True,
        ),
    )
    frames = []
    for i in range(3):
        frame = Image.new("P", (200, 200), 0)  # index 0: black, transparent
        frame.putpalette([0, 0, 0, 200, 30, 30] + [0, 0, 0] * 254)
        frame.paste(1, (100 + i * 10, 0, 200, 200))
        frames.append(frame)
    frames[0].save(
        tmp_path / "hidden_black.gif", format="GIF", save_all=True,
        append_images=frames[1:], duration=80, loop=0, transparency=0, disposal=2,
    )

    saved = await compose_meme("hidden_black", {"top_text": "TOP"})
    out = Image.open(saved.path)

    for frame in ImageSequence.Iterator(out):
        _assert_opaque(frame)
        assert min(frame.convert("RGB").getpixel((50, 150))) >= 240


async def test_canvas_mode_scrim_darkens_the_photo_instead_of_replacing_it(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    photo = Image.new("RGB", (500, 500), (0, 0, 255))

    saved = await compose_meme_on_image(photo, {"top_text": "TOP", "bottom_text": "BOTTOM"})
    out = Image.open(saved.path)

    _assert_opaque(out)
    # Inside the top caption box (x from 5%, y from 2%) at its left edge:
    # scrim, but no caption glyphs. Outside the box the photo is untouched.
    rgb = out.convert("RGB")
    r, g, b = rgb.getpixel((30, 14))
    assert (r, g) == (0, 0)
    assert 100 <= b <= 160
    assert rgb.getpixel((2, 2)) == (0, 0, 255)


async def test_canvas_mode_flattens_a_transparent_photo(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    photo = Image.new("RGBA", (500, 500), (0, 0, 0, 0))

    saved = await compose_meme_on_image(photo, {"top_text": "TOP", "bottom_text": "BOTTOM"})
    out = Image.open(saved.path)

    _assert_opaque(out)
    assert out.convert("RGB").getpixel((250, 250)) == (255, 255, 255)


async def test_arc_card_is_opaque(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    stats = ArcStats(
        has_enough=True,
        total_memes=47,
        period_label="Your Arc",
        aura=12480,
        tier="certified menace",
        top_templates=[ArcTemplate(template_id="drake", display_name="Drake", count=9, roast="(classic)")],
        busiest_time_label="2 AM",
        hour_roast="we're not asking questions.",
        chat_count=26,
        lore_count=15,
        make_count=6,
        split_roast="yappacino.",
        longest_streak_days=6,
        verdict="we've seen growth. we're a little scared.",
    )

    saved = await compose_arc_card(stats)
    _assert_opaque(Image.open(saved.path))
