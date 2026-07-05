# MemeGPT Upgrade — Multimodal Input (Image → Canvas → Video → RAG)

## Context

You are working in the MemeGPT repository. MemeGPT is a chatbot that responds exclusively with memes:

1. User sends a plain-English message
2. An LLM router (currently qwen3.6-27b on Groq) picks the best template from ~100 options, guided by a USE_WHEN dictionary
3. Pillow renders captions onto the template image

Before doing anything, explore the codebase to learn the actual stack, entry points, how the router is called, how rendering works, and whether any upload handling already exists. Read CLAUDE.md if present. Do not assume file names, frameworks, or libraries — verify everything against the real code.

## Mission

Add the ability for users to upload images (and, if feasible, short videos) and get memes generated from them. Work in phases, in this exact order. **Phase 0 blocks everything else.** Present a written plan first (files to touch, libraries to add, provider choices with a rough cost note per request) and wait for my approval before writing any code.

---

## Phase 0 — Upload Safety Gate (NON-NEGOTIABLE, BLOCKING)

No uploaded media may reach any model, disk persistence, or rendering code without passing ALL of the following, in this order. Implement it as a single choke-point function or middleware (e.g., `safe_ingest(upload) -> CleanImage`) so no current or future code path can bypass it.

1. **Size and type limits.** Reject images > 10 MB and videos > 30 seconds or > 50 MB. Validate file type by magic bytes (python-magic, or Pillow open+verify), never by extension or user-supplied MIME type alone.
2. **Decompression-bomb protection.** Set `PIL.Image.MAX_IMAGE_PIXELS` to a deliberate value, catch `DecompressionBombError`, and reject images larger than 8000 px on either side.
3. **Metadata stripping.** Strip ALL metadata (including EXIF GPS) immediately on receipt by re-encoding: load pixels into a fresh image object and save new bytes. Never copy or persist the original upload bytes.
4. **Content moderation.** Every image — and every sampled video frame in Phase 3 — must pass a moderation check before any further processing. Prefer a dedicated moderation endpoint that accepts images; if unavailable, use a vision model with a strict safety rubric. Categorically block: sexual content, any content involving or sexualizing minors, graphic violence/gore, and hate symbols. On failure: refuse with a generic message, do not echo or describe what was detected, delete all temp files, and log a category-only audit record (never the image itself).
5. **Rate limiting** on the upload path, per user or session.
6. **Retention policy.** Uploaded media is deleted immediately after the meme is generated (hard ceiling: 1 hour). Only the generated meme persists. No copies for analytics or anything else.

**Tests required before Phase 1 may start:** oversized file rejected; a renamed `.exe → .jpg` rejected by magic-byte check; EXIF GPS provably absent from output bytes; decompression bomb rejected; moderation-failure path returns a refusal and leaves zero temp files behind. The full test suite must be green.

---

## Phase 1 — Mode 1: Image as Context

**Outcome:** user uploads a photo (plus optional text); a vision model produces a 1–3 sentence situation description; that description feeds into the EXISTING USE_WHEN router unchanged; captioning and Pillow rendering work exactly as today.

Requirements:

- Build the vision call behind a small provider-agnostic interface. Check Groq's currently available vision-capable models for the primary; the Anthropic API (`claude-sonnet-4-6`, native image input) is an acceptable primary or fallback. On vision failure, degrade gracefully: ask the user to describe the image in words.
- The vision prompt must return: the situation, the emotional tone, and any text visible in the image — phrased as if the user had typed it. Merge with the user's own text when both exist.
- Zero changes to the router or renderer. Add a regression test proving every existing text-only flow still passes.

---

## Phase 2 — Mode 2: User Image as Canvas

**Outcome:** the user's already-sanitized photo becomes the meme template itself.

- **v1 (required):** classic top/bottom captions — white Impact-style font, black stroke outline, font size auto-scaled to image width, long lines wrapped. The caption model receives the vision description from Phase 1 and writes `top_text` / `bottom_text`.
- **v2 (stretch, only after v1 ships and works):** face detection (mediapipe or OpenCV) plus a safe-placement step — captions must never cover faces; prefer empty regions the vision model reports.
- Mode selection: infer from wording ("make this a meme" → Mode 2; "react to this" → Mode 1). Default to Mode 1 when ambiguous; allow explicit override.

---

## Phase 3 — Video Support (FEASIBILITY-GATED)

Implement only if ffmpeg is available in the deployment environment AND the app can process asynchronously (or runs locally/CLI where blocking is acceptable). If either fails, write `FEASIBILITY.md` explaining exactly what is missing and stop this phase.

If go:

- Accept video ≤ 30 seconds. Use ffmpeg to sample keyframes (scene-change detection, capped at 5 frames).
- EVERY sampled frame goes through the Phase 0 moderation check before any model sees it.
- The vision model ranks frames for meme potential; the winning frame enters the Phase 1 or Phase 2 flow as a static image.
- Output is a static meme. Captioned GIFs are explicitly out of scope for this pass.
- Delete the video and all frames immediately after generation.

---

## Phase 4 — RAG Template Retrieval (FEASIBILITY-GATED)

Implement only if the template library exceeds ~150 entries OR the router prompt is measurably degrading pick accuracy / exceeding comfortable context. If neither holds, record the trigger criteria in `FEASIBILITY.md` and stop this phase.

If go:

- Embed all USE_WHEN strings (local model such as sentence-transformers/fastembed, or an embeddings API — justify the choice in the plan).
- At request time: embed the user message or vision description, retrieve top-10 candidate templates, and let the existing router LLM choose only among those 10.
- Store embeddings in a local file or SQLite. Do not introduce a vector-database dependency at this scale.
- CLIP-style image→template visual matching is out of scope; note it under future work.

---

## Process Rules

- Plan first; wait for my approval before writing code.
- One phase per commit (or a small set), meaningful messages. Never start phase N+1 with failing tests in phase N.
- All configuration via environment variables; update `.env.example`. Never hardcode keys. Never log image bytes, and keep vision descriptions out of info-level logs.
- Update `CLAUDE.md` with: new commands, provider/model choices, and the invariant "ALL uploaded media enters through safe_ingest — never bypass it."
- Write `docs/UPLOADS.md`: pipeline overview, limits, and the retention policy (this doubles as the user-facing privacy note).

## Definition of Done

I can run the app locally and: upload a test photo and receive a Mode 1 meme and a Mode 2 meme; a > 10 MB file, a fake-extension file, and an unsafe test image are each cleanly refused with temp files cleaned up; the full test suite is green; CLAUDE.md and docs/UPLOADS.md reflect reality.

## Questions

Ask me before coding only if genuinely blocking — e.g., vision provider preference (Groq vs Anthropic) if cost is a concern, or where this deploys (local CLI vs hosted web), since that changes the async and rate-limit design. Otherwise, make reasonable choices and record them in the plan.
