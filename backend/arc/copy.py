"""
Arc's scoring + roast-copy layer. Turns db.RawArcStats (pure aggregates,
no opinions) into the voiced ArcStats API response: the aura score, tier,
per-template roasts, busiest-hour/split/verdict lines.

Coverage guarantee: every one of the ~118 catalog templates resolves to a
non-blank roast. TEMPLATE_ROASTS hand-covers the ~30 most likely top
templates; anything else falls back to _FALLBACK_ROASTS, picked
deterministically per template_id (same template always gets the same
line for a given user, but different templates spread across the pool) —
not a hand-curated semantic category for all 118, which would be more
precision than is actually verifiable, but the same functional guarantee:
nothing ever comes back blank.
"""

from __future__ import annotations

import hashlib
from datetime import date
from zoneinfo import ZoneInfo

from db import RawArcStats
from image_processing.compositor import template_image_url
from schemas import ArcStats, ArcTemplate, ArcTier
from vector_db.chroma_client import get_template_record

_MIN_MEMES_FOR_ARC = 5

# --- Tier ladder ---

_TIER_THRESHOLDS: list[tuple[int, str]] = [
    (2_000, "npc arc"),
    (5_000, "side character energy"),
    (10_000, "main character (unwell)"),
    (17_501, "certified menace"),  # 10k-17.5k inclusive
    (20_000, "baby aura farmer"),  # 17.6k-19.9k — deliberate anticlimax right below god-tier
]
_TOP_TIER = "aura farming god"

# --- Aura formula ---

_LATE_NIGHT_BONUS = 400  # busiest hour landing in the 12am-4am roast bucket


def _compute_aura(raw: RawArcStats, busiest_local_hour: int | None) -> int:
    aura = (
        raw.total_memes * 90
        + raw.longest_streak_days * 250
        + raw.distinct_templates * 75
        + raw.lore_count * 50
        + raw.make_count * 50  # hand-picking the template and writing every
        # caption yourself is at least as much effort as a big Lore dump —
        # same bonus weight, not a guess at a different number
    )
    if busiest_local_hour is not None and busiest_local_hour < 5:
        aura += _LATE_NIGHT_BONUS
    return aura


def _tier_for_aura(aura: int) -> str:
    for threshold, name in _TIER_THRESHOLDS:
        if aura < threshold:
            return name
    return _TOP_TIER


def _tier_ladder() -> list[ArcTier]:
    """Every tier with the lowest aura that earns it, top tier first. Built
    from _TIER_THRESHOLDS, the same list _tier_for_aura grades with, so a
    tier table and its "N to the next tier" line can't drift from the score."""
    floors = [0] + [threshold for threshold, _ in _TIER_THRESHOLDS]
    names = [name for _, name in _TIER_THRESHOLDS] + [_TOP_TIER]
    return [ArcTier(name=name, min_aura=floor) for floor, name in reversed(list(zip(floors, names)))]


def _stable_index(key: str, n: int) -> int:
    """Deterministic pseudo-random pick — the same key always resolves to
    the same option (a template's roast doesn't change between views; a
    verdict is stable within one Arc), but different keys spread across the
    pool instead of every user seeing option 0. Not Python's built-in
    hash() — that's randomized per-process for strings, which would make
    the "same key -> same result" guarantee false across restarts."""
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest, 16) % n


# --- Template roasts ---

TEMPLATE_ROASTS: dict[str, str] = {
    "drake": "(basic, but self-aware)",
    "evil_kermit": "(concerning)",
    "this_is_fine": "(seek help)",
    "hide_the_pain_harold": "(are you okay)",
    "surprised_pikachu": "(you did this to yourself)",
    "grus_plan": "(the plan never works)",
    "expanding_brain": "(reaching, but respect it)",
    "two_buttons": "(commitment issues)",
    "woman_yelling_at_cat": "(unresolved beef, clearly)",
    "buff_doge_vs_cheems": "(delusional, but confident)",
    "mocking_spongebob": "(mocking somebody, no comment on who)",
    "one_does_not_simply": "(dramatic, but valid)",
    "change_my_mind": "(nobody asked, you answered anyway)",
    "panik_kalm_panik": "(emotionally unstable, we love that for you)",
    "distracted_boyfriend": "(loyalty: questionable)",
    "chill_guy": "(the only stable one here)",
    "sad_pablo": "(waiting on a text that's not coming)",
    "waiting_skeleton": "(patience: a myth)",
    "ah_shit_here_we_go_again": "(this keeps happening to you specifically)",
    "mr_incredible_uncanny": "(the vibe shift was documented)",
    "math_lady": "(doing the math on your own life)",
    "roll_safe_think_about_it": "(galaxy brain, technically wrong)",
    "tuxedo_winnie_the_pooh": "(said the same thing, fancier)",
    "epic_handshake": "(finally found common ground)",
    "spiderman_pointing_at_spiderman": "(nobody's taking the blame)",
    "always_has_been": "(the twist you saw coming)",
    "disaster_girl": "(smiling through the chaos you caused)",
    "trade_offer": "(the math wasn't mathing)",
    "is_this_a_pigeon": "(confidently, deeply wrong)",
    "boardroom_meeting_suggestion": "(everyone agreed, everyone was wrong)",
}

_FALLBACK_ROASTS: list[str] = [
    "(a whole personality)",
    "(unwell, but thriving)",
    "(delulu is the solulu)",
    "(manifesting nonsense, respect)",
    "(soft launch of a breakdown)",
    "(genuinely sweet, no notes)",
    "(pick a struggle)",
    "(the pettiness was earned)",
    "(a choice was made)",
    "(iconic, actually)",
]


def _template_roast(template_id: str) -> str:
    if template_id in TEMPLATE_ROASTS:
        return TEMPLATE_ROASTS[template_id]
    return _FALLBACK_ROASTS[_stable_index(template_id, len(_FALLBACK_ROASTS))]


def _display_name(template_id: str) -> str:
    """Mirrors routers/memes.py's _template_display_name — small and
    different enough in null-handling (this caller always has a real
    template_id) that duplicating it here beats a cross-router import."""
    record = get_template_record(template_id)
    if record and record.get("name"):
        return record["name"]
    return template_id.replace("_", " ").title()



# --- Busiest-hour roast (4 buckets, full 24h coverage, 2 lines each) ---

_HOUR_ROASTS: list[tuple[range, list[str]]] = [
    (range(0, 5), ["we're not asking questions.", "certified insomniac behavior."]),
    (range(5, 9), ["who hurt you, and why are you up.", "the earliest of birds, apparently."]),
    (range(9, 18), ["at work, allegedly.", "productivity, redefined."]),
    (range(18, 24), ["peak hours, peak chaos.", "prime-time behavior."]),
]


def _hour_roast(hour: int, seed: str) -> str:
    for hour_range, options in _HOUR_ROASTS:
        if hour in hour_range:
            return options[_stable_index(seed, len(options))]
    return _HOUR_ROASTS[0][1][0]  # unreachable — ranges cover 0-23


# --- Chat vs Lore vs Make split roast ---

def _split_roast(chat_count: int, lore_count: int, make_count: int) -> str:
    total = chat_count + lore_count + make_count
    if total == 0:
        return "blank slate."
    if chat_count == total:
        return "lore-allergic."
    if lore_count == total:
        return "you don't chat, you narrate."
    if make_count == total:
        return "doesn't trust the AI's taste."

    counts = {"chat": chat_count, "lore": lore_count, "make": make_count}
    dominant = max(counts, key=lambda k: counts[k])
    runner_up = max(v for k, v in counts.items() if k != dominant)
    if runner_up == 0 or counts[dominant] > runner_up * 1.5:
        return {
            "chat": "yappacino.",
            "lore": "you don't chat, you narrate.",
            "make": "control freak, and we respect it.",
        }[dominant]
    return "range."


# --- Volume and streak lines ---
# The fixed lead-ins ("memes generated this arc.", "consecutive days.") are
# interface copy; these are the punchlines after them, like hour_roast and
# split_roast.

_VOLUME_ROAST = "no thoughts, just memes."

# One streak length decides both the streak line and the verdict's
# dedication branch, so the two never disagree about what counts as a lot.
_DEDICATED_STREAK_DAYS = 7


def _streak_roast(longest_streak_days: int) -> str:
    return "no days off." if longest_streak_days >= _DEDICATED_STREAK_DAYS else "still an arc."


# --- Closing verdict (priority-ordered, first match wins, 2 lines each) ---

def _verdict(raw: RawArcStats, seed: str) -> str:
    if raw.total_memes < 15:
        options = ["your arc just started. plot: unknown.", "early days. character development: pending."]
    elif raw.longest_streak_days >= _DEDICATED_STREAK_DAYS:
        options = ["no days off. concerning dedication.", "we get it, you're committed."]
    elif raw.distinct_templates <= 2:
        options = ["character development: none detected. Arc continues.", "found a personality and stuck with it."]
    elif raw.distinct_templates >= 8:
        options = ["we've seen growth. we're a little scared.", "range. actual range."]
    elif raw.total_memes >= 100:
        options = ["a whole career, honestly.", "at this point it's a lifestyle."]
    else:
        options = ["plot: lost. vibes: immaculate.", "unbothered and memeing."]
    return options[_stable_index(seed, len(options))]


# --- Season / period label ---

_SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Autumn", 10: "Autumn", 11: "Autumn",
}


def _period_label(first: date, last: date) -> str:
    """"<Season> Arc" when the whole span sits inside one season (~100 days
    or less, same season name) — else the generic "Your Arc" rather than a
    misleading season label for a longer-running account."""
    span_days = (last - first).days
    if span_days <= 100 and _SEASON_BY_MONTH[first.month] == _SEASON_BY_MONTH[last.month]:
        return f"{_SEASON_BY_MONTH[first.month]} Arc"
    return "Your Arc"


def build_arc_stats(raw: RawArcStats | None, tz: str = "UTC") -> ArcStats:
    """None (no Postgres) and "too little data yet" both resolve to the
    same has_enough=False empty state — the frontend doesn't need to
    distinguish them, it just shows the same playful empty state either way."""
    if raw is None or raw.total_memes < _MIN_MEMES_FOR_ARC:
        return ArcStats(has_enough=False, total_memes=raw.total_memes if raw else 0)

    # Stable across repeated views of the same underlying data (same total/
    # span), changes naturally once new memes land — not per-request random,
    # which would make roast lines flicker between rerenders.
    seed = f"{raw.total_memes}:{raw.first_date}:{raw.last_date}"

    busiest_local_hour: int | None = None
    busiest_time_label: str | None = None
    busiest_hour_label: str | None = None
    hour_roast: str | None = None
    if raw.busiest_sample_ts is not None:
        # A real moment on the busiest date, shown beside that date.
        busiest_time_label = raw.busiest_sample_ts.astimezone(ZoneInfo(tz)).strftime("%-I:%M %p")
    if raw.busiest_hour_ts is not None:
        # The busiest hour of day. Its label, roast and late-night bonus all
        # read this one moment, so they always describe the same hour.
        busiest_hour = raw.busiest_hour_ts.astimezone(ZoneInfo(tz))
        busiest_local_hour = busiest_hour.hour
        busiest_hour_label = busiest_hour.strftime("%-I %p")
        hour_roast = _hour_roast(busiest_local_hour, seed)

    aura = _compute_aura(raw, busiest_local_hour)
    tier = _tier_for_aura(aura)

    top_templates = [
        ArcTemplate(
            template_id=template_id,
            display_name=_display_name(template_id),
            count=count,
            roast=_template_roast(template_id),
            image_url=template_image_url(template_id),
        )
        for template_id, count in raw.top_templates
    ]

    period_label = _period_label(raw.first_date, raw.last_date) if raw.first_date and raw.last_date else None

    return ArcStats(
        has_enough=True,
        total_memes=raw.total_memes,
        distinct_templates=raw.distinct_templates,
        date_span_start=raw.first_date.isoformat() if raw.first_date else None,
        date_span_end=raw.last_date.isoformat() if raw.last_date else None,
        period_label=period_label,
        aura=aura,
        tier=tier,
        tiers=_tier_ladder(),
        top_templates=top_templates,
        busiest_date=raw.busiest_date.isoformat() if raw.busiest_date else None,
        busiest_time_label=busiest_time_label,
        busiest_hour_label=busiest_hour_label,
        hour_roast=hour_roast,
        chat_count=raw.chat_count,
        lore_count=raw.lore_count,
        make_count=raw.make_count,
        split_roast=_split_roast(raw.chat_count, raw.lore_count, raw.make_count),
        longest_streak_days=raw.longest_streak_days,
        volume_roast=_VOLUME_ROAST,
        streak_roast=_streak_roast(raw.longest_streak_days),
        verdict=_verdict(raw, seed),
    )
