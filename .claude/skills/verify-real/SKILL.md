---
name: verify-real
description: Verify a change against real services and real data, not mocks. Use before claiming any backend or frontend change works.
context: fork
agent: Explore
---

This repo's test suite cannot catch several real classes of bug. Every one
of these was found by real verification and missed by tests:

- `httpx.ASGITransport` calls FastAPI in-process and never touches Next.js —
  the double-redirect bug on `/arc` and `/me` was invisible to every backend
  test.
- A silently-async call (`upsert_example` without `await`) printed
  "Ingested N rows" while ingesting zero.
- Precomputed embeddings can be present but semantically wrong.

## Procedure

1. Run the change through the **real** code path, not a mock, with real
   services where the change touches them.
2. Assert on the thing you actually care about, not a proxy. If the claim is
   "zero Gemini calls," add a guard that raises if `httpx.post` reaches
   `generativelanguage.googleapis.com` — don't infer it from timing.
3. For frontend changes, hit a **running dev server** and diff rendered HTML.
   `tsc --noEmit` proves nothing about mounting or redirects.
4. For anything touching storage or the DB, use `/safe-verify` first.
5. State plainly in the summary what was verified for real and what was not.
   Do not describe a mocked assertion as a verification.
