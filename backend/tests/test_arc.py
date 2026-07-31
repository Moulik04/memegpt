"""
Growth Phase D — Arc. Pure-logic tests for streak/aura/tier computation
(no DB needed), plus GET /arc/ and POST /arc/card's graceful-absence
behavior with no DATABASE_URL configured (the default test environment).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from arc.copy import _compute_aura, _tier_for_aura, build_arc_stats
from db import RawArcStats, _longest_streak
from httpx import ASGITransport, AsyncClient
from main import app


def test_longest_streak_empty():
    assert _longest_streak([]) == 0


def test_longest_streak_single_day():
    assert _longest_streak([date(2026, 7, 1)]) == 1


def test_longest_streak_consecutive_run():
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 10)]
    assert _longest_streak(dates) == 3


def test_longest_streak_ignores_duplicates():
    dates = [date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 2)]
    assert _longest_streak(dates) == 2


def test_longest_streak_unsorted_input():
    dates = [date(2026, 7, 3), date(2026, 7, 1), date(2026, 7, 2)]
    assert _longest_streak(dates) == 3


def test_tier_boundaries_match_owner_spec():
    assert _tier_for_aura(0) == "npc arc"
    assert _tier_for_aura(1_999) == "npc arc"
    assert _tier_for_aura(2_000) == "side character energy"
    assert _tier_for_aura(4_999) == "side character energy"
    assert _tier_for_aura(5_000) == "main character (unwell)"
    assert _tier_for_aura(9_999) == "main character (unwell)"
    assert _tier_for_aura(10_000) == "certified menace"
    assert _tier_for_aura(17_500) == "certified menace"
    assert _tier_for_aura(17_501) == "baby aura farmer"
    assert _tier_for_aura(19_999) == "baby aura farmer"
    assert _tier_for_aura(20_000) == "aura farming god"


def test_compute_aura_lands_near_owner_reference_example():
    # Owner's own reference voice: "+4,200 aura farmed · 47 memes." Not
    # pinned exact (the formula has room to tune), just order-of-magnitude.
    raw = RawArcStats(total_memes=47, distinct_templates=6, lore_count=35, longest_streak_days=9)
    aura = _compute_aura(raw, busiest_local_hour=2)
    assert 3_000 <= aura <= 12_000


def test_build_arc_stats_none_raw_is_empty_state():
    stats = build_arc_stats(None)
    assert stats.has_enough is False
    assert stats.total_memes == 0


def test_build_arc_stats_below_minimum_is_empty_state():
    stats = build_arc_stats(RawArcStats(total_memes=3))
    assert stats.has_enough is False
    assert stats.total_memes == 3


def test_build_arc_stats_enough_data_populates_everything():
    raw = RawArcStats(
        total_memes=47,
        distinct_templates=6,
        chat_count=12,
        lore_count=35,
        top_templates=[("evil_kermit", 10), ("drake", 8)],
        first_date=date(2026, 6, 1),
        last_date=date(2026, 8, 20),
        busiest_date=date(2026, 7, 12),
        busiest_sample_ts=datetime(2026, 7, 12, 2, 14, tzinfo=timezone.utc),
        longest_streak_days=9,
    )
    stats = build_arc_stats(raw, tz="UTC")
    assert stats.has_enough is True
    assert stats.total_memes == 47
    assert stats.aura > 0
    assert stats.tier is not None
    assert len(stats.top_templates) == 2
    assert stats.top_templates[0].template_id == "evil_kermit"
    assert stats.top_templates[0].roast == "(concerning)"
    assert stats.busiest_time_label == "2:14 AM"
    assert stats.verdict is not None
    assert stats.split_roast is not None
    assert stats.period_label == "Summer Arc"


def test_build_arc_stats_every_template_gets_a_roast_never_blank():
    # A template with no hand-written entry must still resolve to something
    # from the fallback pool, never an empty string.
    raw = RawArcStats(total_memes=10, top_templates=[("some_obscure_template_id", 5)])
    stats = build_arc_stats(raw)
    assert stats.top_templates[0].roast  # non-empty


async def _get(path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def test_get_arc_with_no_anon_header_is_empty_state():
    resp = await _get("/arc/")
    assert resp.status_code == 200
    assert resp.json()["has_enough"] is False


async def test_get_arc_with_anon_header_but_no_database_url_is_empty_state():
    resp = await _get("/arc/", headers={"X-MemeGPT-User": "test-anon-id"})
    assert resp.status_code == 200
    assert resp.json()["has_enough"] is False


async def test_create_arc_card_rejects_not_enough_data():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/arc/card", headers={"X-MemeGPT-User": "test-anon-id"})
    assert resp.status_code == 400
