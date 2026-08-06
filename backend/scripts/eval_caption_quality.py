"""
Growth master-prompt Phase F — pairwise caption-quality judge.

The eval set IS backend/db's few_shot_examples table, not a new query.
memes/feedback are deliberately text-free (see db/schema.sql's own
privacy-rule comment) — there is no situation/caption text to join against
in Postgres. But routers/feedback.py already writes a row into
few_shot_examples (user_message, template_id, texts) precisely when a real
user thumbs-ups a caption with that data present — that table already *is*
"an eval set from Postgres feedback (thumbs-up examples)," fully realized,
no new plumbing needed.

For each stored (real, human-approved) baseline caption, this generates a
fresh *candidate* caption for the same prompt and asks Groq to judge which
is funnier/fits better — twice, with the two captions' positions swapped
between rounds, so a real preference has to survive being asked both ways
before it counts (cancels the well-documented LLM-judge position bias). A
round that disagrees with itself, or where Groq's response was empty/
unparseable (rate-limit noise — see _PACING_SECONDS below and the identical
lesson already learned the hard way in eval_template_matching.py), counts
as "degraded" and is excluded from the win-rate denominator rather than
silently corrupting it.

As shipped, "candidate" means today's live parse_intent() pipeline — this
verifies the harness itself against a real baseline without waiting on a
fine-tuned model to exist. To evaluate an actual fine-tuned model instead,
point local dev's LLM_PROVIDER=ollama at it and rerun this unchanged —
parse_intent() already dispatches through whichever provider config.py is
set to.

Paced like eval_template_matching.py (10s), but this makes 3 Groq calls per
case (1 candidate generation + 2 judge rounds) instead of 1, so budget
accordingly — 20 cases is ~10 minutes.

Run: cd backend && python -m scripts.eval_caption_quality [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Literal

import httpx

import db
from config import get_settings
from nlp.intent_router import parse_intent
from nlp.llm_client import call_groq, strip_markdown

_PACING_SECONDS = 10

Preference = Literal["baseline", "candidate", "tie"]

_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial judge comparing two sets of meme captions written "
    "for the same real-world situation, each for a specific meme template. "
    "Decide which caption set is funnier and fits its template better. "
    'Respond with ONLY valid JSON: {"winner": "A", "reason": "one short '
    'sentence"} where winner is "A", "B", or "tie".'
)


async def fetch_eval_set(limit: int = 20) -> list[dict]:
    rows = await db.fetch_few_shot_examples()
    return rows[:limit]


def _format_captions(template_id: str, texts: dict[str, str]) -> str:
    lines = "\n".join(f"  {box}: {text}" for box, text in texts.items())
    return f"Template: {template_id}\n{lines}"


def _build_judge_prompt(
    situation: str,
    template_a: str,
    texts_a: dict[str, str],
    template_b: str,
    texts_b: dict[str, str],
) -> list[dict]:
    user_content = (
        f"Situation: {situation}\n\n"
        f"Caption set A:\n{_format_captions(template_a, texts_a)}\n\n"
        f"Caption set B:\n{_format_captions(template_b, texts_b)}\n\n"
        "Which caption set is funnier and fits the situation better?"
    )
    return [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _judge_round_to_preference(winner: str, a_is_baseline: bool) -> Preference:
    """winner is "A"/"B"/"tie" from the judge's own perspective for THIS
    round's positions — a_is_baseline tells us which side "A" actually was,
    so both rounds' results land on a shared baseline/candidate/tie scale
    regardless of which position each one occupied."""
    if winner not in ("A", "B"):
        return "tie"
    picked_a = winner == "A"
    picked_baseline = picked_a == a_is_baseline
    return "baseline" if picked_baseline else "candidate"


def _aggregate_judgment(pref_round1: Preference, pref_round2: Preference) -> Preference:
    """A real preference must survive being asked with positions swapped —
    if the two rounds disagree (or either was itself a tie), the case counts
    as a tie rather than trusting whichever round happened to run first."""
    if pref_round1 == pref_round2 and pref_round1 != "tie":
        return pref_round1
    return "tie"


async def _judge(client: httpx.AsyncClient, settings, messages: list[dict]) -> tuple[str, bool]:
    """Returns (winner, degraded) — degraded=True means the raw response was
    empty (both Groq attempts hit 429, see call_groq's own fallback) or
    wasn't valid JSON; the caller excludes degraded rounds from scoring
    rather than letting rate-limit noise masquerade as a real "tie"."""
    raw = await call_groq(client, settings, messages, temperature=0.3)
    if not raw:
        return "tie", True
    try:
        data = json.loads(strip_markdown(raw))
        winner = data.get("winner", "tie")
        return (winner if winner in ("A", "B", "tie") else "tie"), False
    except json.JSONDecodeError:
        return "tie", True


async def run_one(client: httpx.AsyncClient, settings, example: dict) -> dict:
    situation = example["user_message"]
    baseline_template = example["template_id"]
    baseline_texts = example["texts"]

    await asyncio.sleep(_PACING_SECONDS)
    candidate = await parse_intent(situation)
    candidate_template = candidate.template_id
    candidate_texts = candidate.texts

    await asyncio.sleep(_PACING_SECONDS)
    winner_r1, degraded_r1 = await _judge(
        client, settings,
        _build_judge_prompt(situation, baseline_template, baseline_texts, candidate_template, candidate_texts),
    )
    pref_r1 = _judge_round_to_preference(winner_r1, a_is_baseline=True)

    await asyncio.sleep(_PACING_SECONDS)
    winner_r2, degraded_r2 = await _judge(
        client, settings,
        _build_judge_prompt(situation, candidate_template, candidate_texts, baseline_template, baseline_texts),
    )
    pref_r2 = _judge_round_to_preference(winner_r2, a_is_baseline=False)

    degraded = degraded_r1 or degraded_r2
    final = _aggregate_judgment(pref_r1, pref_r2)

    return {
        "situation": situation,
        "baseline_template": baseline_template,
        "candidate_template": candidate_template,
        "template_match": baseline_template == candidate_template,
        "final": final,
        "degraded": degraded,
    }


async def main(limit: int = 20) -> None:
    eval_set = await fetch_eval_set(limit)
    if not eval_set:
        print(
            "No few-shot examples in Postgres yet — nothing to evaluate. "
            "This table is populated by real 👍 feedback with a caption attached "
            "(see routers/feedback.py); generate some real traffic and thumbs-up "
            "a few captions first, or check DATABASE_URL is configured."
        )
        return

    settings = get_settings()
    rows: list[dict] = []
    async with httpx.AsyncClient() as client:
        for example in eval_set:
            r = await run_one(client, settings, example)
            rows.append(r)
            tag = "DEGRADED" if r["degraded"] else r["final"].upper()
            match_tag = "same-template" if r["template_match"] else "DIFF-template"
            print(f"  [{tag:9s}][{match_tag:14s}] {r['situation'][:55]}")

    n = len(rows)
    degraded_rows = [r for r in rows if r["degraded"]]
    scored_rows = [r for r in rows if not r["degraded"]]
    baseline_wins = sum(1 for r in scored_rows if r["final"] == "baseline")
    candidate_wins = sum(1 for r in scored_rows if r["final"] == "candidate")
    ties = sum(1 for r in scored_rows if r["final"] == "tie")
    template_matches = sum(1 for r in rows if r["template_match"])

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Cases:                 {n}")
    if degraded_rows:
        print(f"Degraded (rate-limit/unparseable — excluded below): {len(degraded_rows)}/{n}")
    denom = len(scored_rows) or 1
    print(f"Baseline wins:         {baseline_wins}/{len(scored_rows)} ({100 * baseline_wins / denom:.0f}%)")
    print(f"Candidate wins:        {candidate_wins}/{len(scored_rows)} ({100 * candidate_wins / denom:.0f}%)")
    print(f"Ties (of scored):      {ties}/{len(scored_rows)} ({100 * ties / denom:.0f}%)")
    print(f"Template agreement:    {template_matches}/{n} ({100 * template_matches / n:.0f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Max examples to evaluate")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit))
