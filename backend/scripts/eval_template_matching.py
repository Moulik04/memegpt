"""
Template-matching *accuracy* eval — unlike scripts/eval_intent_models.py
(which measures JSON-parse reliability and template diversity across LLM
providers, with no ground truth), this has a labeled golden set and
measures whether the pick is actually right.

Two separate metrics, because they diagnose different problems:
  - RAG recall: is an acceptable template_id present in the candidate set
    resolve_prompt_template_ids() hands to the LLM? A miss here means no
    amount of USE_WHEN wording could have saved this case — it's a
    retrieval/RAG-tuning problem (Phase 4), not a description problem.
  - Final-pick accuracy: given parse_intent()'s actual end-to-end choice,
    did it match? Isolates prompt/USE_WHEN-wording/LLM-judgment quality,
    separate from whether the candidate set was even right.

Calls resolve_prompt_template_ids() directly (not a hand-copied snapshot,
unlike eval_intent_models.py) so this always reflects intent_router.py's
real current RAG parameters — required for Phase 4's before/after tuning
to mean anything. This does mean the RAG step effectively runs twice per
case (once standalone for the recall check, once again inside
parse_intent()) — a minor, accepted inefficiency in exchange for not
re-implementing parse_intent()'s internals here.

Every pick is tagged with the prompt that produced it, full or retry, and
accuracy is reported for each separately. They are different tasks: the
retry prompt has no examples and is only reached by an unusable reply. One
number for both hid that until 2026-10-10, when a third of a run turned out
to have been answered by the retry prompt.

Paced at 10 seconds a case by default. Groq's free tier is ~8000 tokens a
minute and a pick is close to 3000, so at that pace about one case in three
waits out a rate limit before it is answered (the latency column shows it).
For a run with no waits at all, pass --pacing 28.

--second-model measures the model the router falls back to when the primary
is out for the day. The primary is marked as out, exactly as production
marks it, so every case goes straight to the second model with the retry
prompt. That run spends the second model's own daily budget, not the
primary's.

Run: cd backend && python -m scripts.eval_template_matching [--pacing SECONDS] [--second-model]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx

import nlp.intent_router as intent_router
from config import get_settings
from nlp.intent_router import (
    is_busy_fallback,
    is_fallback,
    parse_intent,
    resolve_prompt_template_ids,
)
from nlp.llm_client import daily_limit_active, mark_daily_limit, strip_markdown
from vector_db.chroma_client import list_template_ids


@dataclass
class GoldenCase:
    message: str
    acceptable_ids: list[str] = field(default_factory=list)


# --- Confusion-cluster cases (core templates) — each targets a specific
# disambiguation the rich USE_WHEN entries were written to make possible.
CORE_CLUSTER_CASES: list[GoldenCase] = [
    GoldenCase("I already picked the boring safe option over the exciting risky one, no regrets", ["drake"]),
    GoldenCase("choosing between two job offers and can't decide, sweating about it", ["two_buttons"]),
    GoldenCase("my responsible self says sleep, my other self says one more episode", ["evil_kermit"]),
    GoldenCase("the old version of the app was a tank, the new version is fragile and weak", ["buff_doge_vs_cheems"]),
    GoldenCase("my roommate screaming about dishes while I calmly sip my tea", ["woman_yelling_at_cat"]),
    GoldenCase("four different ways to fix the bug, ranked from hacky to genius", ["expanding_brain"]),
    GoldenCase("step 1 looked great, step 2 looked great, step 3 is a disaster and I only just noticed", ["grus_plan"]),
    GoldenCase("smiling through the pain of pretending I understand the meeting", ["hide_the_pain_harold"]),
    GoldenCase("someone interrupted me mid-sentence to 'correct' me and they were wrong", ["batman_slapping_robin"]),
    GoldenCase("shocked that ignoring the deadline for two weeks caused a problem", ["surprised_pikachu"]),
    GoldenCase("swerving off my career plan at the last second for a shiny new opportunity", ["left_exit_12"]),
    GoldenCase("an idea gets suggested in the meeting and everyone piles onto it before it gets shot down", ["boardroom_meeting_suggestion"]),
    GoldenCase("asked to just apologize, instead burned the whole relationship down", ["uno_draw_25_cards"]),
    GoldenCase("watching my rival's server crash with a smug little smile", ["disaster_girl"]),
    GoldenCase("two rivals shaking hands because they both hate the new update", ["epic_handshake"]),
    GoldenCase("the same sentence said plainly, then said again with fancy corporate words", ["tuxedo_winnie_the_pooh"]),
    GoldenCase("panic, then a reassuring detail, then realizing it's actually worse", ["panik_kalm_panik"]),
    GoldenCase("confidently mislabeling a duck as a goose", ["is_this_a_pigeon"]),
    GoldenCase("somebody caught red-handed on the kiss cam with the wrong person", ["kiss_cam_caught"]),
    GoldenCase("effortlessly landing the shot while everyone else needed full gear", ["turkish_shooter"]),
    GoldenCase("technically correct answer that is completely wrong in spirit", ["well_yes_but_actually_no"]),
    GoldenCase("the same bad situation starting over again and I'm just tired now", ["ah_shit_here_we_go_again"]),
    GoldenCase("milking sympathy with big sad eyes over something minor", ["sad_hamster"]),
    GoldenCase("one bold debatable opinion stated flatly as fact, daring anyone to argue", ["change_my_mind"]),
    GoldenCase("repeating what someone said back in alternating caps to mock them", ["mocking_spongebob"]),
    GoldenCase("sitting in literal chaos and refusing to acknowledge anything is wrong", ["this_is_fine"]),
    GoldenCase("pointing out that something everyone thinks is easy is actually really hard", ["one_does_not_simply"]),
]

# --- Full-catalog cases — templates that only had a terse one-liner before
# Phase 3's rewrite. Includes explicitly confusable pairs (Leo, Megamind,
# Spider-Man) so the eval can tell whether a rewrite actually helps.
FULL_CATALOG_CASES: list[GoldenCase] = [
    GoldenCase("waited so long for a reply I could have died of old age", ["waiting_skeleton", "sad_pablo"]),
    GoldenCase("pointing with a satisfied little toast at exactly the right moment", ["leonardo_dicaprio_cheers"]),
    GoldenCase("pointing and laughing at something ridiculous I just spotted", ["laughing_leo"]),
    GoldenCase("two identical things each accusing the other of being the fake", ["spiderman_pointing_at_spiderman"]),
    GoldenCase("three versions of the same thing all claiming to be the original", ["spider_man_triple"]),
    GoldenCase("shocked that someone has zero of a completely normal thing", ["megamind_no_bitches"]),
    GoldenCase("peeking in through a tiny window at something I'm not part of", ["megamind_peeking"]),
    GoldenCase("insisting two clearly different things are actually identical", ["theyre_the_same_picture"]),
    GoldenCase("one tiny early mistake that snowballed into a huge disaster", ["domino_effect"]),
    GoldenCase("tapping my temple with a 'genius' loophole that's actually terrible logic", ["roll_safe_think_about_it"]),
    GoldenCase("pulling off the mask to reveal who was secretly behind it all along", ["scooby_doo_mask_reveal"]),
    GoldenCase("reading an uncomfortable truth about myself and immediately throwing it away", ["the_scroll_of_truth"]),
    GoldenCase("crashed my own bike because I was distracted looking at something else", ["bike_fall"]),
    GoldenCase("publicly declaring I've replaced my favorite tool with a shiny new one", ["friendship_ended"]),
    GoldenCase("watching a disaster coming from a mile away and being powerless to stop it", ["a_train_hitting_a_school_bus"]),
    GoldenCase("each step getting closer to doing the dumb thing I swore I wouldn't", ["clown_applying_makeup"]),
    GoldenCase("the same argument going in circles across five back-and-forth exchanges", ["american_chopper_argument"]),
    GoldenCase("calling something genuinely great or ironically overhyped 'peak cinema'", ["absolute_cinema"]),
    GoldenCase("the counter-offer is way less than what I was expecting", ["pawn_stars_best_i_can_do"]),
    GoldenCase("an overkill dramatic fix applied with total unearned confidence", ["flex_tape"]),
    GoldenCase("calmly explaining why I am nothing like someone clearly inferior", ["gus_fring_we_are_not_the_same"]),
]

GOLDEN_SET: list[GoldenCase] = CORE_CLUSTER_CASES + FULL_CATALOG_CASES

_PACING_SECONDS = 10  # bumped from 7s — cumulative Groq usage across repeated
# eval runs in one session empirically triggered heavy rate-limiting that
# manifested as parse_intent()'s hard fallback firing on most cases rather
# than genuine wrong picks, silently corrupting an earlier run's results.
# More pacing headroom reduces how often this happens; intent_router's own
# is_fallback() means an unavoidable one gets caught either way. It is what
# distinguishes "LLM genuinely picked wrong" from "Groq rate-limited/timed
# out and parse_intent() silently returned its hardcoded hide_the_pain_harold
# fallback," which looks identical in template_id alone.


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Template-matching accuracy eval against the golden set.")
    parser.add_argument(
        "--pacing", type=float, default=_PACING_SECONDS, metavar="SECONDS",
        help=f"seconds between cases (default and minimum {_PACING_SECONDS}; 28 avoids every rate-limit wait)",
    )
    parser.add_argument(
        "--second-model", action="store_true",
        help="mark the primary model as out for the day so every case is answered by the second model",
    )
    args = parser.parse_args(argv)
    if args.pacing < _PACING_SECONDS:
        parser.error(f"--pacing cannot go below {_PACING_SECONDS} seconds")
    return args


def outcome_tag(row: dict) -> str:
    # No pick comes first: the canned meme is itself a template one golden
    # case expects, and a fallback there is still not a right answer.
    if row["is_busy"]:
        return "BUSY"
    if row["is_fallback"]:
        return "FALLBACK"
    return "OK" if row["final_hit"] else "WRONG"


@dataclass(frozen=True)
class ProviderError:
    """The provider answered with an HTTP error instead of a reply."""

    status: int
    code: str | None


def reply_kind(raw: str | ProviderError | None) -> str:
    """What the model's last reply for a case was, before any validation:
    "clean" (it parses as JSON), "malformed", "empty", "error" for a
    provider error, or "none" when nothing came back at all. A clean reply
    can still be unusable: a made-up template id, or captions under labels
    the template does not have.

    Groq checks JSON itself when asked for a JSON object, and answers 400
    json_validate_failed in place of output that does not parse. That is the
    model's malformed JSON, so it is counted as such."""
    if raw is None:
        return "none"
    if isinstance(raw, ProviderError):
        return "malformed" if raw.code == "json_validate_failed" else "error"
    if not raw.strip():
        return "empty"
    try:
        json.loads(strip_markdown(raw))
    except json.JSONDecodeError:
        return "malformed"
    return "clean"


def reply_counts(rows: list[dict]) -> dict[str, int]:
    return dict(Counter(row["reply"] for row in rows))


# Every raw reply (or provider error) for the case in hand, oldest first.
_replies: list[str | ProviderError] = []


def _provider_error(exc: httpx.HTTPStatusError) -> ProviderError:
    try:
        code = (exc.response.json().get("error") or {}).get("code")
    except ValueError:
        code = None
    return ProviderError(exc.response.status_code, code)


def _record_replies() -> None:
    """Wraps the router's model call so the harness sees each raw reply. The
    router itself only says whether a reply was usable."""
    real_call = intent_router.call_llm

    async def recording_call(*args, **kwargs) -> str:
        try:
            raw = await real_call(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            _replies.append(_provider_error(exc))
            raise
        _replies.append(raw)
        return raw

    intent_router.call_llm = recording_call


def accuracy_by_prompt(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """(right, answered) for each prompt that answered at least one case.
    A case with no pick (a canned fallback, a busy answer) belongs to
    neither prompt."""
    counts: dict[str, tuple[int, int]] = {}
    for row in rows:
        if row["is_fallback"] or not row["prompt"]:
            continue
        right, answered = counts.get(row["prompt"], (0, 0))
        counts[row["prompt"]] = (right + (1 if row["final_hit"] else 0), answered + 1)
    return counts


async def run_one(case: GoldenCase, known_ids: set[str]) -> dict:
    prompt_ids = await resolve_prompt_template_ids(case.message, known_ids)
    rag_hit = any(tid in prompt_ids for tid in case.acceptable_ids)

    _replies.clear()
    t0 = time.monotonic()
    result = await parse_intent(case.message)
    latency = time.monotonic() - t0
    fallback_hit = is_fallback(result)
    final_hit = not fallback_hit and result.template_id in case.acceptable_ids

    return {
        "message": case.message,
        "acceptable_ids": case.acceptable_ids,
        "rag_hit": rag_hit,
        "final_hit": final_hit,
        "is_fallback": fallback_hit,
        "is_busy": is_busy_fallback(result),
        "prompt": result.prompt_used,
        "model": result.model_used,
        "reply": reply_kind(_replies[-1] if _replies else None),
        "picked": result.template_id,
        "latency": latency,
    }


# Long enough to outlast any run. The mark lives in this process only.
_PRIMARY_MARKED_OUT_SECONDS = 6 * 3600.0


async def main(pacing: float = _PACING_SECONDS, second_model: bool = False) -> None:
    known_ids = set(list_template_ids())
    if not known_ids:
        print("ChromaDB is empty — run the backend once first to auto-seed templates.")
        return

    settings = get_settings()
    model_under_test = settings.groq_model
    if second_model:
        if settings.llm_provider != "groq" or settings.groq_fallback_model in ("", settings.groq_model):
            print("--second-model needs LLM_PROVIDER=groq and a second model different from the primary.")
            return
        mark_daily_limit(settings.groq_model, _PRIMARY_MARKED_OUT_SECONDS)
        model_under_test = settings.groq_fallback_model
        print(f"Primary model marked as out for the day. Every case goes to {model_under_test}.\n")
    _record_replies()

    rows: list[dict] = []
    for i, case in enumerate(GOLDEN_SET):
        if i > 0:
            await asyncio.sleep(pacing)
        r = await run_one(case, known_ids)
        if daily_limit_active(model_under_test):
            # The model's daily budget ran out on this case. From here on
            # the router answers from another model or not at all, so
            # nothing more would measure the model under test, and every
            # further case would only dig into the same empty budget.
            print(
                f"\nSTOPPED at case {i + 1} of {len(GOLDEN_SET)}: the model's daily budget is "
                f"used up. That case is not counted. The summary covers the {len(rows)} before it."
            )
            break
        rows.append(r)
        rag_tag = "RAG-OK" if r["rag_hit"] else "RAG-MISS"
        answered_by = "-" if not r["prompt"] else (r["prompt"] if r["model"] == "primary" else f"{r['prompt']}/2nd")
        reply_note = "" if r["reply"] == "clean" else f"  [reply: {r['reply']}]"
        print(
            f"  [{rag_tag:8s}][{outcome_tag(r):8s}][{answered_by:9s}] {r['latency']:5.2f}s  "
            f"{r['message'][:55]:55s} -> {r['picked']}"
            + ("" if r["final_hit"] else f"  (expected: {'/'.join(r['acceptable_ids'])})")
            + reply_note
        )

    n = len(rows)
    if not n:
        print("No cases completed.")
        return
    fallback_rows = [r for r in rows if r["is_fallback"]]
    scored_rows = [r for r in rows if not r["is_fallback"]]  # exclude infra noise from accuracy
    rag_recall = sum(1 for r in rows if r["rag_hit"])
    final_accuracy = sum(1 for r in scored_rows if r["final_hit"])

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Cases:                       {n}")
    print(f"RAG recall:                  {rag_recall}/{n} ({100 * rag_recall / n:.0f}%)")
    if fallback_rows:
        busy = sum(1 for r in fallback_rows if r["is_busy"])
        print(
            f"No pick (excluded from accuracy below, not a real pick): {len(fallback_rows)}/{n} "
            f"({busy} busy, {len(fallback_rows) - busy} canned fallback)"
        )
    print(
        f"Final-pick accuracy (of {len(scored_rows)} cases with a pick): "
        f"{final_accuracy}/{len(scored_rows)} "
        f"({100 * final_accuracy / len(scored_rows) if scored_rows else 0:.0f}%)"
    )
    for prompt, (right, answered) in sorted(accuracy_by_prompt(rows).items()):
        print(f"  answered by the {prompt} prompt:    {right}/{answered} ({100 * right / answered:.0f}%)")
    by_second_model = sum(1 for r in scored_rows if r["model"] == "second")
    if by_second_model:
        print(f"  of those, answered by the second model: {by_second_model}")
    kinds = reply_counts(rows)
    print(
        "Last reply per case:         "
        + ", ".join(f"{kinds.get(kind, 0)} {kind}" for kind in ("clean", "malformed", "empty", "error", "none"))
    )
    unusable_clean = sum(1 for r in fallback_rows if r["reply"] == "clean")
    if unusable_clean:
        print(f"  clean JSON that still could not be used (unknown template or labels): {unusable_clean}")

    rag_misses = [r for r in rows if not r["rag_hit"]]
    if rag_misses:
        print("\nRAG misses (retrieval problem, not fixable by wording alone):")
        for r in rag_misses:
            print(f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])})")

    final_misses = [r for r in scored_rows if r["rag_hit"] and not r["final_hit"]]
    if final_misses:
        print("\nFinal-pick misses despite correct candidate set (wording/LLM-judgment problem):")
        for r in final_misses:
            print(
                f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])}, "
                f"got: {r['picked']}, {r['prompt']} prompt)"
            )

    if fallback_rows:
        print("\nCases with no pick (rerun these individually if you need a clean read on them):")
        for r in fallback_rows:
            print(f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])})")


if __name__ == "__main__":
    _args = parse_args()
    asyncio.run(main(_args.pacing, _args.second_model))
