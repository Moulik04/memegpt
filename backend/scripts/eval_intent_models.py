"""
Standalone comparison harness: qwen/qwen3.6-27b (current production default)
vs openai/gpt-oss-120b, both on Groq, on the exact prompt-construction path
parse_intent() uses (same catalog, same system template) — but instrumented
to report attempt-1 success/failure directly instead of silently retrying
into the hardcoded fallback the way parse_intent() does for callers.

There's no labeled "correct template" ground truth for these prompts, so
this measures what's actually measurable: JSON-parse success rate, valid-
known-template-id rate, latency, and template diversity — plus prints a
side-by-side of picks for manual eyeballing.

Run: cd backend && python -m scripts.eval_intent_models
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
from pydantic import ValidationError

from config import Settings, get_settings
from nlp.intent_router import _build_template_catalog, _normalize_llm_response, _CORE_TEMPLATE_IDS
from nlp.llm_client import call_groq, strip_markdown
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids, query_similar_memes

MODELS = ["qwen/qwen3.6-27b", "openai/gpt-oss-120b"]

TEST_SITUATIONS = [
    "waiting for my PR to get reviewed for 3 days",
    "my plan was going great then suddenly it wasn't",
    "me vs my alarm clock at 7am",
    "when the deploy finally works on first try",
    "my friend after 4 drinks claiming he's sober",
    "my manager asking who broke production",
    "choosing between two job offers and can't decide, sweating about it",
    "I already picked the boring safe option over the exciting risky one, no regrets",
    "my roommate screaming about dishes while I calmly sip my tea",
    "four different ways to fix the bug, ranked from hacky to genius",
    "step 1 looked great, step 2 looked great, step 3 is a disaster and I only just noticed",
    "smiling through the pain of pretending I understand the meeting",
    "someone interrupted me mid-sentence to 'correct' me and they were wrong",
    "the old version of the app was a tank, the new version is fragile and weak",
    "shocked that ignoring the deadline for two weeks caused a problem",
    "swerving off my career plan at the last second for a shiny new opportunity",
    "my responsible self says sleep, my other self says one more episode",
    "an idea gets suggested in the meeting and everyone piles onto it before it gets shot down",
    "asked to just apologize, instead burned the whole relationship down",
    "watching my rival's server crash with a smug little smile",
    "two rivals shaking hands because they both hate the new update",
    "the same sentence said plainly, then said again with fancy corporate words",
    "panic, then a reassuring detail, then realizing it's actually worse",
    "confidently mislabeling a duck as a goose",
    "somebody caught red-handed on the kiss cam with the wrong person",
    "effortlessly landing the shot while everyone else needed full gear",
    "technically correct answer that is completely wrong in spirit",
    "the same bad situation starting over again and I'm just tired now",
    "milking sympathy with big sad eyes over something minor",
    "one small ask ignored in favor of an absurdly costly alternative",
]


async def run_one(client: httpx.AsyncClient, model: str, situation: str, known_ids: set[str]) -> dict:
    settings = Settings(
        groq_api_key=get_settings().groq_api_key,
        llm_provider="groq",
        groq_model=model,
    )

    rag_results = query_similar_memes(situation, n_results=8)
    rag_ids = [r["id"] for r in rag_results if r.get("id") in known_ids]
    core_set = set(_CORE_TEMPLATE_IDS)
    extra_rag = [i for i in rag_ids if i not in core_set]
    prompt_ids = (_CORE_TEMPLATE_IDS + extra_rag)[:25]
    catalog = _build_template_catalog(prompt_ids)

    from nlp.intent_router import _SYSTEM_TEMPLATE

    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2),
        few_shot_block="",
        avoid_block="",
    )

    t0 = time.monotonic()
    try:
        raw = await call_groq(client, settings, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": situation},
        ])
        latency = time.monotonic() - t0
        raw = strip_markdown(raw)
        data = json.loads(raw)
        data = _normalize_llm_response(data, known_ids)
        result = IntentResponse(**data)
        valid_id = result.template_id in known_ids
        return {
            "ok": True,
            "valid_id": valid_id,
            "template_id": result.template_id,
            "texts": result.texts,
            "latency": latency,
        }
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response is not None else str(exc)
        return {"ok": False, "error": f"HTTPStatusError {exc.response.status_code}: {detail}", "latency": time.monotonic() - t0}
    except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "latency": time.monotonic() - t0}


async def main() -> None:
    known_ids = set(list_template_ids())
    if not known_ids:
        print("ChromaDB is empty — run the backend once first to auto-seed templates.")
        return

    results: dict[str, list[dict]] = {m: [] for m in MODELS}
    async with httpx.AsyncClient() as client:
        for model in MODELS:
            print(f"\n=== {model} ===")
            for i, situation in enumerate(TEST_SITUATIONS):
                if i > 0:
                    # Groq's free tier is ~8000 tokens/min and each call here
                    # runs ~700-900 tokens (25-template catalog in the system
                    # prompt) — back-to-back calls blow through that budget
                    # and 429 within ~10 requests. Pace to stay under it.
                    await asyncio.sleep(7)
                r = await run_one(client, model, situation, known_ids)
                results[model].append(r)
                tag = "OK" if r["ok"] and r.get("valid_id") else ("BAD_ID" if r["ok"] else "FAIL")
                picked = r.get("template_id", r.get("error", ""))
                print(f"  [{tag:6s}] {r['latency']:.2f}s  {situation[:50]:50s} -> {picked}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for model in MODELS:
        rows = results[model]
        n = len(rows)
        json_ok = sum(1 for r in rows if r["ok"])
        valid_id = sum(1 for r in rows if r["ok"] and r["valid_id"])
        avg_latency = sum(r["latency"] for r in rows) / n
        picks = [r["template_id"] for r in rows if r["ok"] and r["valid_id"]]
        diversity = len(set(picks)) / len(picks) if picks else 0
        print(f"\n{model}:")
        print(f"  JSON parse success (attempt 1): {json_ok}/{n} ({100 * json_ok / n:.0f}%)")
        print(f"  Valid known template_id:        {valid_id}/{n} ({100 * valid_id / n:.0f}%)")
        print(f"  Avg latency:                    {avg_latency:.2f}s")
        print(f"  Template diversity (unique/total): {diversity:.2f}")
        failures = [r for r in rows if not r["ok"]]
        if failures:
            print(f"  Failures:")
            for f in failures:
                print(f"    - {f['error']}")


if __name__ == "__main__":
    asyncio.run(main())
