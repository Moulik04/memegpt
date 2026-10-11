---
name: eval-run
description: Run the template-matching, caption-quality, or intent-model eval harnesses correctly. Use before and after any USE_WHEN, prompt, RAG, or model change.
allowed-tools: Read Bash(python*)
---

Four harnesses, four different questions:

| Script | Answers |
|---|---|
| `eval_template_matching.py` | RAG recall (retrieval) vs final-pick accuracy (LLM judgment), against a labeled golden set |
| `eval_caption_quality.py` | Position-swapped judge, baseline vs candidate captions |
| `eval_intent_models.py` | JSON-parse reliability across Groq text models, no ground truth |
| `eval_segmentation.py` | Lore's moment-splitting on pastes with a known number of moments: is an explicit count honoured, does anything repeat, and how many real moments were found |

## Non-negotiables

- **Pacing decides what a run measures.** Groq's free tier is ~8000
  tokens/min and one template pick is close to 3000. At 10 seconds a case
  about one case in three meets the per-minute limit, so a 10s run of
  `eval_template_matching.py` measures rate limits, not the model. Run it at
  25 to 30 seconds a case (`--pacing 28`), where no case waits. 10s is the
  harness's floor and the other harnesses' pace. Never go below it.
- **Always log which prompt answered, and read accuracy per prompt.** The
  harness tags every case `full` or `retry` (`retry/2nd` for the second
  model) and prints accuracy for each. They are different tasks, and one
  number for both hid a retry prompt that could only offer 14 templates: a
  2026-10-10 run read 71% overall, and by timing its fast answers were 31 of
  32 right and its slow ones 3 of 16. Any change to the router, to either
  prompt, or to the harness has to keep this record. Production writes the
  same thing as a `router_pick prompt=... model=...` log line.
- **Always check `IntentResponse.reasoning` for hard-fallback hits and
  exclude them from the denominator.** A `hide_the_pain_harold` fallback is
  indistinguishable from a genuine bad pick without this. An earlier run
  reported "23% accuracy" that was entirely rate-limit exhaustion. The
  harness does this itself (`FALLBACK` and `BUSY` rows) and says how many
  cases had no pick.
- **Read the first lines of output before letting a run continue.** A line
  starting `[examples_store]` about an embedding dimension means the local
  example store was built with the other embedding backend, and the router
  is running without its few-shot examples. Stop, and run against a copy of
  the index whose examples were built with the backend in use.
- **For local wording iteration, run with `GEMINI_API_KEY=` unset.** Gemini's
  free tier has a 1000 req/day cap that no retry gets past. Local embeddings
  use zero quota and reseed near-instantly. Note in the results that local
  RAG recall (~96%) is lower than Gemini's (100%), so numbers across the two
  backends are not apples-to-apples.
- **Report both metrics separately.** A miss with correct retrieval is a
  wording problem; a miss without it is a retrieval problem. They have
  different fixes.

- **For `eval_segmentation.py`, read the printed moments, not just the
  counts.** "Moments found" compares a number against a number. A run can
  hit the expected count with the wrong split, and a repeat told in entirely
  different words gets past the word-overlap check the harness shares with
  production. Run it before and after any change to `nlp/segmentation.py`'s
  prompts, temperatures, output budget, or near-duplicate thresholds.

## Baseline

48-case golden set, real Groq + Gemini, `--pacing 28`, 2026-10-11: 48/48 RAG
recall, 47/48 final-pick accuracy, every case answered by the full prompt on
the primary model. It is one answer per case on a small hand-written set, so
it is a regression check, not a benchmark. A new run compares with it only
if it was paced the same way and the per-prompt lines show the full prompt
answered everything.

The earlier "75%" baseline, and the 67% and 72% measured against it, came
from 10s runs that mixed full-prompt and retry-prompt answers. Do not
compare against them.

Retrieval is not the bottleneck: recall has been 48/48 on every Gemini run,
and RAG parameter tuning was investigated and ruled out on evidence.

`--second-model` marks the primary as out for the day, the way production
does, so every case is answered by the second model with the retry prompt.
It spends that model's own daily budget, which is separate from the
primary's.
