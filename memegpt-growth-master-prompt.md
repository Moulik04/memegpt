# MemeGPT Growth — Watermark, Share Pages, Memory, Wrapped, Trends, Fine-tune, Distribution

## Context

Read CLAUDE.md first, then explore before assuming anything. This spec covers seven
phases (A–G). Order is strict for A → B → C → D (each depends on the last). E and F
are independent and may be interleaved anytime after A. G is last.

**The zero-cost constraint is absolute:** free tiers only, and the app must boot,
pass all tests, and behave exactly as today when NONE of the new env vars are set.
Every external dependency in this spec is feature-flagged with graceful absence —
missing creds mean the feature silently disables (one startup log line), never a
crash.

Present a written plan per phase and wait for approval before code. At each phase
boundary, ask me for exactly the credentials that phase needs — not all upfront.

## Prerequisites I will provide when asked

- Phase B: Supabase project (`DATABASE_URL`) and a Cloudflare R2 bucket
  (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
  `R2_PUBLIC_BASE_URL`).
- Phase E: `GROQ_API_KEY` as a GitHub Actions repo secret.
- Phase F: I run the Colab training myself — you stop at the handoff.
- Phase G: Discord application creds (`DISCORD_PUBLIC_KEY`, `DISCORD_APP_ID`,
  `DISCORD_BOT_TOKEN`) and a Cloudflare Workers account.

---

## Phase A — Watermark (no new services)

1. `compositor.py`: new `_draw_watermark(img)` applied to EVERY generated meme —
   catalog templates, canvas mode, and /generate/. A small "memegpt" wordmark,
   bottom-right corner: semi-transparent white with a subtle dark stroke, height
   ~3.5% of image height (minimum 12px), consistent padding. Drawn AFTER captions.
   Smooth and unobtrusive is the requirement — recognizable, not shouting; never
   reposition or shrink caption boxes to accommodate it.
2. Config: `watermark_enabled` (default true) and `watermark_text` in settings.
3. Provenance layer: embed a PNG `tEXt` chunk (`memegpt_id: <meme_id>` once Phase B
   ids exist; a random id until then). Document honestly in CLAUDE.md that most
   platforms strip metadata on re-encode — the visible mark is the durable one.
4. Tests: output with flag on differs from flag off; watermark present in canvas
   mode; caption rendering unchanged (existing tests stay green).

## Phase B — Durable storage + share pages

1. **Meme storage interface** (`backend/storage/`): `save_meme(png_bytes) ->
   {meme_id, public_url}` with two backends — R2 (S3-compatible, boto3 is an
   acceptable new dependency) and the current local `static/generated/` fallback
   when creds are absent. `meme_id` = random 10-char base62, unguessable. No
   listing endpoint, ever.
2. **Postgres layer** (Supabase): tables for `memes` (id, url, template_id, mode,
   anon_user_id nullable, created_at), `feedback`, and `few_shot_examples`.
   PRIVACY RULE: do NOT store situation text, dump text, or captions in Phase B —
   template ids and metadata only.
3. **Fix the amnesia:** move feedback + few-shot examples to Postgres as the source
   of truth; on startup, re-hydrate the ChromaDB examples collection from Postgres
   (ChromaDB stays ephemeral-but-rebuildable, like templates). `log_usage` writes
   Postgres when available.
4. **Share pages:** backend `GET /memes/{id}` (url + template display name only) and
   a frontend `/m/[id]` page rendering the meme with full `og:image` / Twitter card
   tags and a "Make your own" CTA into /chat. Verify unfurl locally with a card
   validator approach and document it.
5. Tests run green with no creds (flags off) plus mocked-store tests for the R2
   path.

## Phase C — Anonymous identity + Memory v1

1. Frontend generates a UUID once into `localStorage` (`memegpt_uid`), sent as an
   `X-MemeGPT-User` header on chat, image, and feedback calls. No signup — the
   landing page promise stays true.
2. **Humor profile:** aggregate per anon user from feedback (loved/hated template
   ids). Feed `parse_intent` a short bounded hint ("user tends to enjoy X-style
   templates; avoid Y") and extend `avoid_templates` across sessions from the DB.
3. **Lore lexicon (STRICTLY OPT-IN):** a toggle in the Lore composer ("Remember
   this group's lore"). When on, one extra LLM call extracts recurring
   names/nicknames/running jokes as short phrases; store ONLY the extracted
   lexicon, never raw dump text. Inject the lexicon into segmentation + intent
   prompts so future memes can make callbacks. Default OFF.
4. **Forget me:** `DELETE /me` endpoint + a small "Forget me" control (deletes all
   rows for the anon id, clears localStorage). Update the privacy line in Lore and
   docs/UPLOADS.md.
5. Everything degrades cleanly when `DATABASE_URL` is absent.

## Phase D — Meme Wrapped

1. Stats endpoint keyed by the anon id (total memes, top 3 templates, busiest day,
   Chat vs Lore split, longest streak). Private: reachable only with the anon id;
   sharing is an explicit act, never a public listing.
2. `/wrapped` page with a staged card-by-card reveal (reuse the existing motion
   patterns from the landing page), plus a Pillow-rendered share card (reuse the
   compositor + watermark) that gets its own `/m/{id}` via Phase B — sharing
   Wrapped uses the same infrastructure as sharing a meme.
3. Playful empty state below 5 generated memes. Copy tone matches the landing page
   (no em dashes in visible copy — existing rule).

## Phase E — Trend pipeline (GitHub Actions, human-in-the-loop)

1. Weekly scheduled workflow: fetch Imgflip's public `get_memes` API (official,
   free — do NOT scrape Know Your Meme or other sites; ToS risk), diff against the
   repo's template set, and for genuinely new candidates: download the image,
   have the LLM (Groq, paced under free-tier TPM — reuse the pacing lesson from
   eval_intent_models.py) draft a USE_WHEN with NOT-FOR language plus a note on
   whether DEFAULT_BOXES suffices or a custom TextBoxConfig is needed.
2. Output: a PR (never auto-merge) adding the image + draft configs, with a review
   checklist that includes checking the new USE_WHEN against the existing confusion
   clusters. The repo is the database; I am the reviewer.
3. A local dry-run mode (`--dry-run`, no PR, no network beyond Imgflip) so the
   script is testable; a unit test covers the diff logic with fixtures.

## Phase F — Fine-tune preparation + humor evals (STOP at training)

1. Verify the existing pipeline end-to-end on a SMALL local sample (no GPU):
   `ingest_imgflip_dataset.py` → `prepare_finetune_dataset.py` → train-ready files.
   Fix bit-rot only; no redesign.
2. Produce a Colab T4 QLoRA config (small, budget-realistic) and
   `docs/FINETUNE_RUNBOOK.md`: exact cells/commands, expected artifacts (GGUF +
   adapter), and how to load the result via the existing `scripts/Modelfile`.
3. Extend the eval harness: build an eval set from Postgres feedback
   (thumbs-up examples as references), and add a pairwise LLM-judge script
   (baseline vs candidate captions, position-swapped double judging to reduce
   order bias, Groq as judge, paced).
4. **HARD STOP:** you do not run training. Production swap is out of scope unless
   a genuinely free serving path exists — document the options honestly in the
   runbook (e.g., offline-eval-only vs. small-model self-hosting trade-offs).

## Phase G — Distribution: Discord bot + GIF templates (feasibility-gated)

1. **Discord slash command** (`/meme <text>`): implement as HTTP interactions, not
   a gateway bot — backend endpoint with ed25519 signature verification. Because
   Discord requires a 3-second ack and Render cold-starts in ~30s, ship a tiny
   Cloudflare Worker (code lives in `integrations/discord-worker/`, I deploy it)
   that acks with a deferred response, forwards to the backend, and PATCHes the
   follow-up with the meme URL (Phase B public URLs make this trivial). Rate-limit
   the endpoint. If the Worker step is skipped, document the limitation and stop —
   do not ship a bot that times out.
2. **GIF templates:** support `type: "gif"` catalog entries — per-frame caption
   burn (Pillow frames or ffmpeg, whichever benchmarks acceptably on Render),
   output size cap ~8MB, frame-count cap. Seed 3–5 classic animated templates with
   USE_WHENs; if per-meme render time on the deployed box exceeds ~10s, gate GIFs
   behind a feasibility note instead of shipping slow.

---

## Non-negotiables (all phases)

- `safe_ingest()` remains the only media entry point; moderation's
  category-never-echoed invariant unchanged.
- Never store or log raw dump text, captions from dumps, or situation text; the
  lexicon is the only derived-from-dump artifact and it is opt-in + deletable.
- Unguessable ids everywhere; no listing/enumeration endpoints; rate limits on
  every new public endpoint (share intake precedent).
- App boots and tests pass with zero new env vars. One phase per commit set.
  CLAUDE.md + relevant docs updated every phase.

## Definition of done (overall)

Every generated meme is watermarked; with creds set, memes persist across restarts
at permanent /m/ URLs that unfurl with og tags; feedback survives restarts and
re-hydrates ChromaDB; anonymous memory influences template picks and "Forget me"
works; /wrapped renders with a shareable card; the weekly Action opens a
reviewable PR when Imgflip surfaces a new template; the fine-tune runbook executes
cleanly up to the training handoff; the Discord command returns a meme through the
worker path; a GIF template renders under the size cap or is documented as gated.
