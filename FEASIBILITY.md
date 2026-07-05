# Phase 3 (Video Support) — Feasibility Check

Per `memegpt-multimodal-master-prompt.md`: "Implement only if ffmpeg is
available in the deployment environment AND the app can process
asynchronously (or runs locally/CLI where blocking is acceptable). If
either fails, write FEASIBILITY.md explaining exactly what is missing and
stop this phase."

**Result: one condition confirmed, one condition genuinely unresolved.
Stopping here rather than designing/implementing against an unconfirmed
assumption, per the master prompt's own instruction.**

## Condition 1 — ffmpeg availability: CONFIRMED

Render's native Python runtime (`env: python` in `render.yaml`, MemeGPT
backend's actual deployment mode) lists `ffmpeg` by name under both the
"Builds" and "Deploys" tool sections of Render's own native-runtimes
documentation (verified via two independent direct fetches of
https://render.com/docs/native-runtimes, quoting the actual page content
rather than an AI-search-summarized version — a first summarization pass
included a suspiciously specific unverifiable version number that didn't
reappear on direct re-fetch, so it was discarded as unreliable rather than
repeated here). No Docker migration or system-package installation step
appears to be needed to get `ffmpeg` itself on the box.

## Condition 2 — async-capable processing: NOT CONFIRMED

The master prompt's bar is "the app can process asynchronously (or runs
locally/CLI where blocking is acceptable)." MemeGPT is a deployed live web
service (Render + Vercel), not a local CLI tool, so the "or runs
locally/CLI" escape clause doesn't apply — this needs to genuinely hold for
the hosted deployment.

Today's image pipeline (Phase 0/1/2, plus the multi-context/multi-meme
batch feature) works within an ordinary HTTP request lifetime by using SSE
to stream progress over one held-open connection, with `maxDuration = 60`
set on the Vercel route handlers to accommodate a several-meme sequential
batch. Video introduces a materially different cost profile per request:

- ffmpeg keyframe/scene-change sampling on a Render free-tier CPU (no
  GPU) for up to a 30-second video, of unknown but plausibly
  non-trivial duration.
- Every sampled frame (capped at 5 per the master prompt) must independently
  pass the Phase 0 moderation gate before anything else touches it — each
  one is its own vision-model round trip, same cost as one Phase 0/1 image
  today, just multiplied by up to 5.
- The vision model then ranks the surviving frames for "meme potential" —
  at least one more vision call.
- Only after all of that does the winning frame enter the existing Phase
  1/2 image flow.

Stacked together, and combined with Render's free-tier ~30s cold-start
penalty already documented in `CLAUDE.md`, this plausibly pushes total
request time well past what even a 60s-and-rising `maxDuration` budget
comfortably covers — and unlike the multi-meme batch (which just needed a
bigger number), there's no existing measurement to extrapolate from,
because nothing in this codebase has ever run ffmpeg or done multi-step
vision ranking before. I have no way to get a real number for "how long
does this actually take on the deployed free-tier box" without either
running it there or committing to an architecture up front — and the
master prompt asks for the feasibility call to be made *before* that
implementation work, not discovered partway through it.

## What's actually blocking a decision

Two different paths forward, and picking between them is a product/cost
decision, not a technical one I should make unilaterally:

1. **Keep today's synchronous-request-per-submission pattern** (extend the
   existing SSE-per-request model to video) and accept that some video
   submissions may occasionally time out on Render's free tier, especially
   right after a cold start — mitigated by capping video length/size
   tightly (the master prompt already caps at ≤30s / ≤50MB) and hoping the
   real-world timing lands inside budget. Cheap to build, genuinely
   uncertain to work reliably without deploying and measuring.
2. **Restructure video processing as an actual background job** (accept
   the upload immediately, return a job id, process in a background task,
   let the client poll or reconnect for the result) — this is a new
   architectural pattern nothing in this codebase uses today (everything
   is request-scoped SSE), a bigger design investment than Phase 3's
   scope implies, and changes the user-facing UX from "watch it stream in"
   to "check back in a bit."

## Recommendation

Before designing Phase 3 further, either:
- **(a)** greenlight a small, cheap feasibility probe — a throwaway
  endpoint that runs `ffmpeg -i <test-clip> ...` on the actual deployed
  Render service and reports wall-clock time, so path 1 above can be
  evaluated with a real number instead of a guess, or
- **(b)** decide up front to commit to path 2 (background job) regardless
  of what a timing probe would show, in which case Phase 3's design should
  start from that architecture rather than extending the current
  synchronous pattern.

Not doing either yet — this file exists so that decision is made
knowingly rather than discovered as a production incident after Phase 3
ships. No code changes accompany this file.
