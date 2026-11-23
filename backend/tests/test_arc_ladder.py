"""
GET /arc's tier ladder, volume and streak lines and busiest hour, which the
Arc story shows in its finale and frames 01, 03 and 05.

The ladder is the point: a tier table and its "N to the next tier" line are
only honest if they come from the same thresholds that grade the score.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from arc.copy import (
    _DEDICATED_STREAK_DAYS,
    _streak_roast,
    _tier_for_aura,
    _tier_ladder,
    _verdict,
    build_arc_stats,
)
from db import RawArcStats


def _raw(**overrides) -> RawArcStats:
    base = dict(
        total_memes=47,
        distinct_templates=14,
        chat_count=26,
        lore_count=15,
        make_count=6,
        top_templates=[("drake", 9)],
        first_date=date(2026, 9, 3),
        last_date=date(2026, 11, 17),
        busiest_date=date(2026, 10, 2),
        busiest_sample_ts=datetime(2026, 10, 2, 2, 14, tzinfo=UTC),
        longest_streak_days=6,
    )
    base.update(overrides)
    return RawArcStats(**base)


def test_the_ladder_runs_top_down_from_the_grading_thresholds():
    ladder = _tier_ladder()
    assert [(t.name, t.min_aura) for t in ladder] == [
        ("aura farming god", 20_000),
        ("baby aura farmer", 17_501),
        ("certified menace", 10_000),
        ("main character (unwell)", 5_000),
        ("side character energy", 2_000),
        ("npc arc", 0),
    ]


@pytest.mark.parametrize("rung", range(6))
def test_each_rung_starts_exactly_where_the_grading_does(rung):
    ladder = _tier_ladder()
    tier = ladder[rung]
    assert _tier_for_aura(tier.min_aura) == tier.name
    if tier.min_aura > 0:
        # One point less is the rung below.
        assert _tier_for_aura(tier.min_aura - 1) == ladder[rung + 1].name


def test_the_handoff_sample_is_5021_from_the_next_tier():
    ladder = _tier_ladder()
    assert _tier_for_aura(12_480) == "certified menace"
    above = ladder[[t.name for t in ladder].index("certified menace") - 1]
    assert (above.name, above.min_aura - 12_480) == ("baby aura farmer", 5_021)


def test_stats_carry_the_ladder_and_the_new_lines():
    stats = build_arc_stats(_raw(), tz="UTC")
    assert stats.tiers == _tier_ladder()
    assert stats.tier in [t.name for t in stats.tiers]
    assert stats.volume_roast == "no thoughts, just memes."
    assert stats.streak_roast == "still an arc."
    assert stats.busiest_hour_label == "2 AM"
    # The hour and its roast describe the same moment.
    assert stats.busiest_time_label == "2:14 AM"
    assert stats.hour_roast in ("we're not asking questions.", "certified insomniac behavior.")


def test_the_hour_follows_the_callers_time_zone():
    stats = build_arc_stats(_raw(busiest_sample_ts=datetime(2026, 10, 2, 18, 5, tzinfo=UTC)), tz="America/New_York")
    assert (stats.busiest_time_label, stats.busiest_hour_label) == ("2:05 PM", "2 PM")


def test_the_empty_state_sends_none_of_it():
    stats = build_arc_stats(RawArcStats(total_memes=2))
    assert stats.tiers == []
    assert stats.volume_roast is None and stats.streak_roast is None and stats.busiest_hour_label is None


@pytest.mark.parametrize(
    ("days", "line"),
    [(0, "still an arc."), (1, "still an arc."), (6, "still an arc."), (7, "no days off."), (30, "no days off.")],
)
def test_streak_lines_by_length(days, line):
    assert _streak_roast(days) == line


def test_the_streak_line_and_the_verdict_agree_on_dedication():
    """The verdict's dedication lines start at the same length as "no days
    off."; below it, the verdict never calls a streak dedicated."""
    dedicated = {"no days off. concerning dedication.", "we get it, you're committed."}
    for days in range(0, 15):
        raw = _raw(total_memes=40, longest_streak_days=days)
        for seed in ("a", "b", "c"):
            assert (_verdict(raw, seed) in dedicated) == (days >= _DEDICATED_STREAK_DAYS)
