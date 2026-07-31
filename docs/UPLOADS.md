# Image Uploads — Pipeline, Limits, and Privacy

This doubles as the user-facing privacy note for MemeGPT's photo-upload
feature (Phase 1: "image as context"). If you're wondering what happens to a
photo you upload, this page has the whole answer.

## The invariant

**Every uploaded image passes through `backend/uploads/safe_ingest.py`'s
`safe_ingest()` function before anything else touches it — no model, no
disk write, no renderer.** No code path in this app is allowed to bypass it.

## Pipeline, in order

1. **Size and type check.** Images over 10MB are rejected. The file type is
   determined by reading the first bytes of the file itself (its "magic
   number"), never by trusting the filename extension or the browser-supplied
   MIME type — a file renamed `virus.exe` → `photo.jpg` is rejected here
   regardless of its name.
2. **Decompression-bomb protection.** Images are capped at 8000 pixels on
   either side. This blocks maliciously crafted files designed to consume
   huge amounts of memory when decoded.
3. **Metadata stripping.** Before anything else happens, the image is
   completely rebuilt from its raw pixels into a brand-new image object.
   This guarantees all EXIF metadata — including GPS location tags your
   phone's camera may embed — is gone. This happens in memory; the original
   file bytes (with their original metadata) are never written to disk and
   never persist anywhere.
4. **Content moderation.** Every image is checked by an AI safety classifier
   before any further processing. Sexual content, content involving minors,
   graphic violence, and hate symbols are all blocked. If an image is
   rejected here, you'll see a generic message — MemeGPT never describes or
   echoes back what it detected, and only a category label (never the image
   itself) is logged for our own abuse-monitoring purposes.
5. **Rate limiting.** The upload endpoint is rate-limited per user to guard
   against abuse.
6. **Retention.** Nothing about the upload persists beyond generating your
   meme. The original photo is never written to disk in the first place —
   it exists only in memory for the duration of your request, and is
   discarded the moment your meme is generated (or the request fails). Any
   future feature that does need to write a file to disk (e.g. video
   support) is required to register it for guaranteed deletion within one
   hour, even if that code crashes before cleaning up after itself.

## Limits summary

| Limit | Value |
|---|---|
| Max image size | 10 MB |
| Max image dimension | 8000 px (either side) |
| Accepted formats | JPEG, PNG, WEBP |
| Rate limit | 5 requests/minute per client |
| Retention | None for the original — deleted from memory immediately after use |

## What happens after an image passes the safety gate

A vision model produces a short, plain-language description of the photo
(the scene, the mood, and any visible text) — phrased as if you'd typed it
yourself. That description is merged with any caption text you typed and
fed into the exact same meme-template picker MemeGPT already uses for
text-only messages. The photo itself is never stored, published, or used to
train anything — only the resulting meme (the same rendered PNG you see in
the chat) is kept, exactly like every other meme this app generates.

## Anonymous memory and Forget me

Separately from the upload pipeline above, MemeGPT keeps a small amount of
memory tied to a random id your browser generates for itself — no signup,
no email, no account.

- **No-signup identity.** The first time you use MemeGPT, your browser
  generates a random id and saves it in `localStorage` on your device.
  It's sent along with your chat/image/feedback requests as a header so
  the app can recognize repeat visits from the same browser. It's never
  tied to your name, email, or any other identifying information.
- **Template memory.** MemeGPT remembers which meme templates it's picked
  for you recently — across sessions, not just within one conversation —
  so it's less likely to repeat itself.
- **Humor profile.** If you consistently 👍 or 👎 certain templates, MemeGPT
  picks up on that as a light preference signal. It's never a hard rule,
  just a nudge.
- **Lore lexicon — strictly opt-in, off by default.** Lore's composer has a
  "Remember this group's lore" toggle. When it's on, MemeGPT extracts short
  recurring names, nicknames, and running jokes from what you paste — never
  the raw text itself — so future memes can make callbacks. Turning it off
  just means nothing new gets extracted; anything already remembered stays
  until you erase it.
- **Forget me.** A "Forget me" link is available from the header on both
  Chat and Lore. It permanently deletes every row tied to your anon id —
  generated memes' association with you, your feedback history, and any
  saved lore — and clears the id from your device, so the next request
  starts completely fresh.

None of this applies if `DATABASE_URL` isn't configured on the server
(e.g. local dev without Postgres) — the app works identically, just without
memory across visits.

## For developers

- `backend/uploads/safe_ingest.py` — the choke-point described above.
- `backend/uploads/moderation.py` — the content-safety check (step 4).
- `backend/uploads/retention.py` — forward-looking TTL cleanup
  infrastructure (not yet exercised — nothing is written to disk today).
- `backend/nlp/vision.py` — the vision description call (Groq primary,
  optional Anthropic fallback).
- `POST /chat/image/` — the endpoint (see `backend/routers/chat.py`).
- `backend/identity.py` — reads the `X-MemeGPT-User` header (Growth Phase C).
- `backend/nlp/lexicon.py` — the opt-in Lore lexicon extraction call.
- `backend/routers/me.py` — `DELETE /me/`, the Forget-me endpoint.
- `frontend/src/lib/identity.ts` — generates/persists the anon id client-side.

Configuration lives in `backend/config.py` / `.env.example` — see
`MAX_IMAGE_BYTES`, `MAX_IMAGE_DIMENSION_PX`, `MODERATION_MODEL`,
`VISION_PROVIDER`, `VISION_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
`UPLOAD_RATE_LIMIT`, `UPLOAD_RETENTION_SECONDS`.
