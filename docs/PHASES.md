# Growth Phases

MemeGPT's feature set beyond the core chat-to-meme pipeline shipped as
eight staged phases, each landed as its own set of tested commits. Summary
below; the corresponding code lives in the paths named in each entry.

- **Phase A — Watermark & provenance.** Every generated meme gets a small
  semi-transparent brand watermark and an embedded PNG provenance tag,
  applied uniformly across catalog templates, canvas mode, and on-demand
  generation (`image_processing/compositor.py`).
- **Phase B — Durable storage + share pages.** Generated memes and
  feedback persist across deploys: `storage.save_meme()` writes to
  Cloudflare R2 (local disk when unconfigured), and Postgres (`memes`,
  `feedback`, `few_shot_examples`) replaces what used to live only in
  ephemeral state. `GET /memes/{id}` and a Next.js share page (`/m/[id]`)
  serve public, single-lookup pages with Open Graph tags. Both
  integrations are optional — unset credentials fall back to a
  fully-functional zero-cost default.
- **Phase C — Anonymous identity + memory v1.** A no-signup anonymous id
  (set client-side in `localStorage`) unlocks cross-session
  personalization: a feedback-derived humor profile nudges future
  template picks, an opt-in "remember lore" toggle extracts recurring
  names and callbacks from Lore-mode conversations, and a "Forget me"
  control erases everything tied to that id.
- **Phase D — Arc, personal meme stats.** A roast-flavored personal
  recap ("Arc"), scored in a vanity unit called aura, built from real
  per-surface usage data. Gated at a minimum activity threshold; produces
  a shareable rendered card through the same storage/share-page path as
  any other meme (`arc/copy.py`, `routers/arc.py`).
- **Phase E — Trend pipeline.** A weekly, human-in-the-loop GitHub
  Actions job scans public template sources, filters near-duplicates of
  the existing catalog via perceptual hashing, drafts a catalog entry for
  genuinely new candidates, and opens a PR for review — it never
  auto-merges (`scripts/trend_pipeline.py`, `.github/workflows/`).
- **Phase F — Fine-tune preparation + humor evals.** Prepares (without
  running) LoRA fine-tuning of a local model on a public meme-caption
  dataset — ingestion, formatting, and a documented handoff for the
  actual GPU training step. Also extends the eval suite with a
  caption-quality judge comparing real approved captions against freshly
  generated ones (`scripts/eval_caption_quality.py`).
- **Phase G — GIF templates + Discord.** Adds animated GIF meme
  templates rendered with a pure-Pillow, no-ffmpeg pipeline, and a
  Discord slash command. Discord's protocol-required signature
  verification and fast acknowledgment live in a small edge worker (not
  the main backend, which isn't always warm), forwarding to a backend
  endpoint gated by a shared secret (`integrations/discord-worker/`,
  `routers/discord.py`).
- **Phase H — Optional accounts + chat history.** Layers optional
  sign-in (email + Google, via Supabase Auth) on top of the anonymous
  system. Signed-in users get persisted chat history with a sidebar;
  deleting a chat also un-teaches its contribution to personalization
  data. Anonymous use is unaffected, and no data-handling disclosure copy
  is shown anywhere (`auth.py`, `routers/conversations.py`).

Implementation history and the reasoning behind specific decisions within
each phase are tracked separately for internal development use.
