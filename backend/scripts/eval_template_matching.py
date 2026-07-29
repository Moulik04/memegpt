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

Paced at the same ~7s/case as eval_intent_models.py — Groq's free tier is
~8000 tokens/min and each parse_intent() call burns a comparable budget.

Run: cd backend && python -m scripts.eval_template_matching
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from nlp.intent_router import parse_intent, resolve_prompt_template_ids
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
# manifested as parse_intent()'s hard fallback firing on most cases (see
# _is_fallback below) rather than genuine wrong picks, silently corrupting
# an earlier run's results. More pacing headroom reduces how often this
# happens; _is_fallback below means an unavoidable one gets caught either way.

# The exact reasoning strings intent_router.py's two hard-fallback sites use
# — matching on these distinguishes "LLM genuinely picked wrong" from "Groq
# rate-limited/timed out and parse_intent() silently returned its hardcoded
# hide_the_pain_harold fallback," which looks identical in template_id alone.
_FALLBACK_REASONING_MARKERS = (
    "Fallback: timed out before producing a result",
    "Fallback: model failed to produce valid JSON on both attempts",
)


async def run_one(case: GoldenCase, known_ids: set[str]) -> dict:
    prompt_ids = await resolve_prompt_template_ids(case.message, known_ids)
    rag_hit = any(tid in prompt_ids for tid in case.acceptable_ids)

    t0 = time.monotonic()
    result = await parse_intent(case.message)
    latency = time.monotonic() - t0
    is_fallback = (result.reasoning or "") in _FALLBACK_REASONING_MARKERS
    final_hit = result.template_id in case.acceptable_ids

    return {
        "message": case.message,
        "acceptable_ids": case.acceptable_ids,
        "rag_hit": rag_hit,
        "final_hit": final_hit,
        "is_fallback": is_fallback,
        "picked": result.template_id,
        "latency": latency,
    }


async def main() -> None:
    known_ids = set(list_template_ids())
    if not known_ids:
        print("ChromaDB is empty — run the backend once first to auto-seed templates.")
        return

    rows: list[dict] = []
    for i, case in enumerate(GOLDEN_SET):
        if i > 0:
            await asyncio.sleep(_PACING_SECONDS)
        r = await run_one(case, known_ids)
        rows.append(r)
        rag_tag = "RAG-OK" if r["rag_hit"] else "RAG-MISS"
        final_tag = "OK" if r["final_hit"] else ("FALLBACK" if r["is_fallback"] else "WRONG")
        print(
            f"  [{rag_tag:8s}][{final_tag:8s}] {r['latency']:.2f}s  "
            f"{r['message'][:55]:55s} -> {r['picked']}"
            + ("" if r["final_hit"] else f"  (expected: {'/'.join(r['acceptable_ids'])})")
        )

    n = len(rows)
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
        print(
            f"Hard-fallback hits (excluded from accuracy below — Groq rate-limit/"
            f"timeout noise, not a real pick): {len(fallback_rows)}/{n}"
        )
    print(
        f"Final-pick accuracy (of {len(scored_rows)} non-fallback cases): "
        f"{final_accuracy}/{len(scored_rows)} "
        f"({100 * final_accuracy / len(scored_rows) if scored_rows else 0:.0f}%)"
    )

    rag_misses = [r for r in rows if not r["rag_hit"]]
    if rag_misses:
        print(f"\nRAG misses (retrieval problem, not fixable by wording alone):")
        for r in rag_misses:
            print(f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])})")

    final_misses = [r for r in scored_rows if r["rag_hit"] and not r["final_hit"]]
    if final_misses:
        print(f"\nFinal-pick misses despite correct candidate set (wording/LLM-judgment problem):")
        for r in final_misses:
            print(f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])}, got: {r['picked']})")

    if fallback_rows:
        print(f"\nHard-fallback hits (rerun these individually if you need a clean read on them):")
        for r in fallback_rows:
            print(f"  - {r['message'][:60]} (expected: {'/'.join(r['acceptable_ids'])})")


if __name__ == "__main__":
    asyncio.run(main())
