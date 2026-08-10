---
name: eval-run
description: Run the template-matching, caption-quality, or intent-model eval harnesses correctly. Use before and after any USE_WHEN, prompt, RAG, or model change.
allowed-tools: Read Bash(python*)
---

Three harnesses, three different questions:

| Script | Answers |
|---|---|
| `eval_template_matching.py` | RAG recall (retrieval) vs final-pick accuracy (LLM judgment), against a labeled golden set |
| `eval_caption_quality.py` | Position-swapped judge, baseline vs candidate captions |
| `eval_intent_models.py` | JSON-parse reliability across Groq text models, no ground truth |

## Non-negotiables

- **Rate limits corrupt eval data silently.** Groq's free tier is ~8000
  tokens/min; a naive loop blows through it in ~10 requests. Every harness
  paces at 10s. Do not reduce it.
- **Always check `IntentResponse.reasoning` for hard-fallback hits and
  exclude them from the denominator.** A `hide_the_pain_harold` fallback is
  indistinguishable from a genuine bad pick without this. An earlier run
  reported "23% accuracy" that was entirely rate-limit exhaustion.
- **For local wording iteration, run with `GEMINI_API_KEY=` unset.** Gemini's
  free tier has a 1000 req/day cap that no retry gets past. Local embeddings
  use zero quota and reseed near-instantly. Note in the results that local
  RAG recall (~96%) is lower than Gemini's (100%), so numbers across the two
  backends are not apples-to-apples.
- **Report both metrics separately.** A miss with correct retrieval is a
  wording problem; a miss without it is a retrieval problem. They have
  different fixes.

## Baseline

48-case golden set, real Groq + Gemini: 100% RAG recall, 75% final-pick
accuracy. Retrieval is not the bottleneck — RAG parameter tuning was
investigated and ruled out on evidence. Pull the wording lever, not the
`n_results` lever.
