---
name: growth-phase
description: Start a new growth phase or major feature. Use when beginning any multi-commit piece of work.
disable-model-invocation: true
---

The established workflow on this repo, in order:

1. **Read `docs/DECISIONS.md`** for anything relevant. Do not re-attempt an
   approach that was already investigated and ruled out (HF image
   embeddings, RAG parameter tuning, Imgflip GIF sourcing, local JWT
   decoding) without new evidence that the blocking constraint has changed.
2. **Write the plan first.** Scope, the staged commits, what each stage
   verifies, and — explicitly — which credentials or external setup this
   phase needs. Ask for exactly those, not everything upfront. Wait for
   approval before writing code.
3. **Stage into landable commits.** Each one green against the full suite on
   its own.
4. **Verify per `/verify-real`.** Real services, real data, `/safe-verify`
   for anything that could write.
5. **Update the docs** at the end: invariants and rules into `CLAUDE.md`,
   the narrative and any incidents into `docs/DECISIONS.md`.

Flag plan deviations as they happen, with the reason. Several past
deviations were correct (Discord verification moving to the Worker, the
`lore_lexicon` PK constraint forcing a different upsert target) — the value
is in the deviation being visible, not in avoiding it.
