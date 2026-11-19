"""
The Arc share card's two styles. "glow" is the original card and stays the
default for POST /arc/card. "frontpage" is the white tabloid card, rendered
only when a request asks for it, with strict fonts and the watermark's
corner kept clear.
"""

from __future__ import annotations

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import image_processing.compositor as compositor
from arc.copy import _display_name
from config import Settings
from image_processing.compositor import _arc_season_line, _watermark_box, compose_arc_card
from main import app
from schemas import ArcStats, ArcTemplate
from storage import SavedMeme


def _fake_settings(monkeypatch, **overrides):
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    monkeypatch.setattr("storage.get_settings", lambda: settings)
    return settings


@pytest.fixture(autouse=True)
def _fresh_font_cache():
    compositor._archivo.cache_clear()
    compositor._anton.cache_clear()
    yield
    compositor._archivo.cache_clear()
    compositor._anton.cache_clear()


def _stats(**overrides) -> ArcStats:
    base = dict(
        has_enough=True,
        total_memes=47,
        distinct_templates=14,
        date_span_start="2026-09-03",
        date_span_end="2026-11-17",
        period_label="Autumn Arc",
        aura=12480,
        tier="certified menace",
        top_templates=[ArcTemplate(template_id="drake", display_name="Drake", count=9, roast="(basic)")],
        chat_count=26,
        lore_count=15,
        make_count=6,
        longest_streak_days=6,
        verdict="we've seen growth. we're a little scared.",
    )
    base.update(overrides)
    return ArcStats(**base)


def _pixels(saved) -> np.ndarray:
    return np.asarray(Image.open(saved.path).convert("RGBA"))


# --- Rendering ---


async def test_default_style_is_the_glow_card(monkeypatch):
    _fake_settings(monkeypatch)
    default = await compose_arc_card(_stats())
    glow = await compose_arc_card(_stats(), style="glow")
    assert np.array_equal(_pixels(default), _pixels(glow))


async def test_unknown_style_is_refused(monkeypatch):
    _fake_settings(monkeypatch)
    with pytest.raises(ValueError):
        await compose_arc_card(_stats(), style="neon")


async def test_frontpage_card_is_a_full_size_opaque_image(monkeypatch):
    _fake_settings(monkeypatch, watermark_enabled=True)
    saved = await compose_arc_card(_stats(), style="frontpage")
    img = Image.open(saved.path)
    assert img.size == (1080, 1350)
    assert img.convert("RGBA").getchannel("A").getextrema() == (255, 255)


async def test_frontpage_card_differs_from_the_glow_card(monkeypatch):
    _fake_settings(monkeypatch)
    glow = await compose_arc_card(_stats())
    frontpage = await compose_arc_card(_stats(), style="frontpage")
    assert not np.array_equal(_pixels(glow), _pixels(frontpage))


async def test_frontpage_card_leaves_the_watermark_corner_blank(monkeypatch):
    # Rendered without the watermark, nothing else may touch its corner.
    _fake_settings(monkeypatch, watermark_enabled=False)
    saved = await compose_arc_card(_stats(), style="frontpage")
    x0, y0, x1, y1 = _watermark_box((1080, 1350))
    corner = _pixels(saved)[y0:y1, x0:x1, :3]
    assert (corner == 255).all()


@pytest.mark.parametrize(
    "top_templates",
    [
        [],
        [ArcTemplate(template_id="spinning_dancer", display_name="Spinning Dancer", count=3, roast="")],
        [ArcTemplate(template_id="american_chopper_argument", display_name="American Chopper", count=1, roast="")],
        [ArcTemplate(template_id="no_such_template", display_name="Gone", count=2, roast="")],
    ],
    ids=["no-template", "gif", "very-tall", "missing-file"],
)
async def test_frontpage_card_renders_any_top_template(monkeypatch, top_templates):
    _fake_settings(monkeypatch)
    saved = await compose_arc_card(_stats(top_templates=top_templates), style="frontpage")
    assert Image.open(saved.path).size == (1080, 1350)


async def test_frontpage_card_has_no_fallback_for_archivo(monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(compositor, "_ARCHIVO_PATH", tmp_path / "missing.ttf")
    with pytest.raises(OSError):
        await compose_arc_card(_stats(), style="frontpage")


async def test_frontpage_card_has_no_fallback_for_anton(monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(compositor, "_ANTON_PATHS", (tmp_path / "missing.ttf",))
    with pytest.raises(FileNotFoundError):
        await compose_arc_card(_stats(), style="frontpage")


def test_archivo_ships_in_the_repo():
    assert compositor._ARCHIVO_PATH.is_file()
    assert (compositor.FONTS_DIR / "OFL-Archivo.txt").is_file()


# --- Season line ---


def test_season_line_with_its_date_range():
    assert _arc_season_line(_stats()) == "AUTUMN ARC • SEP 3\u2013NOV 17, 2026"


def test_season_line_for_a_single_day():
    stats = _stats(date_span_start="2026-11-17", date_span_end="2026-11-17")
    assert _arc_season_line(stats) == "AUTUMN ARC • NOV 17, 2026"


def test_season_line_across_a_new_year():
    stats = _stats(period_label="Winter Arc", date_span_start="2026-12-20", date_span_end="2027-02-10")
    assert _arc_season_line(stats) == "WINTER ARC • DEC 20, 2026\u2013FEB 10, 2027"


def test_your_arc_keeps_its_date_range():
    stats = _stats(period_label="Your Arc", date_span_start="2026-06-02", date_span_end="2026-11-17")
    assert _arc_season_line(stats) == "YOUR ARC • JUN 2\u2013NOV 17, 2026"


def test_season_line_without_dates_is_your_arc():
    stats = _stats(period_label=None, date_span_start=None, date_span_end=None)
    assert _arc_season_line(stats) == "YOUR ARC"


def test_archivo_has_the_en_dash():
    font = compositor._archivo(30, 700)
    # A missing glyph renders as the same .notdef box as any other unmapped
    # character; the en dash must not match it.
    assert font.getmask("\u2013").getbbox() != font.getmask("\uffff").getbbox()


# --- Template layout: below the text, or in a right-hand column ---


def _plan_for(template_id: str, **overrides):
    stats = _stats(
        top_templates=[ArcTemplate(template_id=template_id, display_name=_display_name(template_id), count=9, roast="")],
        **overrides,
    )
    template = compositor._arc_template_image(template_id)
    return compositor._frontpage_plan(stats, template.size)


def test_tall_template_moves_to_the_column_and_at_least_doubles_its_area():
    plan = _plan_for("american_chopper_argument")
    assert plan.layout == "column"
    assert plan.area_column >= 2 * plan.area_below
    # The column starts level with the top of the red score block.
    assert plan.mat[1] == plan.score_block[1]


def test_gif_template_stays_below_the_text():
    assert _plan_for("spinning_dancer").layout == "below"


def test_wide_template_stays_below_the_text():
    assert _plan_for("midwit_bell_curve").layout == "below"


def test_six_digit_score_leaves_the_column_clear_of_the_left_column():
    plan = _plan_for("american_chopper_argument", aura=123456, tier="aura farming god")
    assert plan.layout == "column"
    gap = compositor._FP_COLUMN_GAP
    assert plan.mat[0] >= plan.score_block[2] + gap
    assert plan.mat[0] >= plan.tier_block[2] + gap
    verdict_font = compositor._archivo(52, 800)
    for line in plan.verdict_lines:
        assert compositor._FP_MARGIN + verdict_font.getlength(line) <= plan.mat[0] - gap


def test_column_label_never_splits_the_count():
    plan = _plan_for("american_chopper_argument")
    assert plan.label_lines[-1].endswith("• 9 times")
    assert sum(line.count("•") for line in plan.label_lines) == 1
    assert all(line.strip() != "•" for line in plan.label_lines)


# --- POST /arc/card ---


@pytest.fixture
def _card_endpoint(monkeypatch):
    """Enough stats for a card, no database, and a compose stub that
    records which style the endpoint asked for."""
    styles: list[str] = []

    async def fake_stats(anon_user_id, user_id, tz):
        return _stats()

    async def fake_compose(stats, style="glow"):
        styles.append(style)
        return SavedMeme(meme_id="abc", url="/static/generated/abc.png", path=None)

    async def fake_insert_meme(**kwargs):
        return None

    monkeypatch.setattr("routers.arc._stats_for_identity", fake_stats)
    monkeypatch.setattr("routers.arc.compose_arc_card", fake_compose)
    monkeypatch.setattr("routers.arc.db.insert_meme", fake_insert_meme)
    return styles


async def _post_card(query: str = ""):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/arc/card{query}", headers={"X-MemeGPT-User": "test-anon-id"})


async def test_card_endpoint_defaults_to_glow(_card_endpoint):
    resp = await _post_card()
    assert resp.status_code == 200
    assert _card_endpoint == ["glow"]


async def test_card_endpoint_renders_frontpage_on_request(_card_endpoint):
    resp = await _post_card("?style=frontpage")
    assert resp.status_code == 200
    assert _card_endpoint == ["frontpage"]


async def test_card_endpoint_rejects_an_unknown_style(_card_endpoint):
    resp = await _post_card("?style=neon")
    assert resp.status_code == 422
    assert _card_endpoint == []
