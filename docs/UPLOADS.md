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
   phone's camera may embed — is gone. The original file bytes (with their
   original metadata) are never saved by the app. A small upload stays in
   memory. Above roughly 1MB the web framework holds the upload in an
   unnamed temporary file while the request runs, and that file is gone
   when the request ends.
4. **Content moderation.** Every image is checked by an AI safety classifier
   before any further processing. Sexual content, content involving minors,
   graphic violence, and hate symbols are all blocked. If an image is
   rejected here, you'll see a generic message — MemeGPT never describes or
   echoes back what it detected, and only a category label (never the image
   itself) is logged for our own abuse-monitoring purposes. The check runs
   on Groq, so the image is sent there. If Groq is rate limiting, the check
   waits and retries for up to about 45 seconds. If it still can't run, the
   image is not processed and you are asked to try again in a minute. An
   image is never let through unchecked.
5. **Rate limiting.** The upload endpoint is rate-limited per user to guard
   against abuse.
6. **Retention.** The original photo is held only for the duration of your
   request and is discarded when your meme is generated or the request
   fails. There are two things that outlast the request. If you ask for
   your own photo to be captioned ("make this a meme"), the captioned copy
   with its metadata removed is the meme, and it is stored like any other
   meme. And a photo sent through your phone's share sheet waits in server
   memory for about 10 minutes so the app can pick it up, then is dropped
   if it was never collected. Any future feature that needs to write a file
   to disk (e.g. video support) is required to register it for guaranteed
   deletion within one hour, even if that code crashes before cleaning up
   after itself.

## Limits summary

| Limit | Value |
|---|---|
| Max image size | 10 MB |
| Max image dimension | 8000 px (either side) |
| Accepted formats | JPEG, PNG, WEBP |
| Rate limit | 5 requests/minute per client |
| Retention | None for the original. It is dropped when the request ends |

## What happens after an image passes the safety gate

A vision model produces a short, plain-language description of the photo
(the scene, the mood, and any visible text) — phrased as if you'd typed it
yourself. That description is merged with any caption text you typed and
fed into the exact same meme-template picker MemeGPT already uses for
text-only messages. The photo itself is not stored or published, and
MemeGPT trains nothing on it. Only the resulting meme (the same rendered
PNG you see in the chat) is kept, exactly like every other meme this app
generates. The exception is the one described under Retention above: when
you ask for your own photo to be captioned, the captioned copy is the meme.

## What is remembered, and Forget me

Separately from the upload pipeline above, MemeGPT keeps a small amount of
memory tied to a random id your browser generates for itself. No signup, no
email, no account.

The first time you use MemeGPT, your browser generates a random id and
saves it in `localStorage` on your device. It is sent along with your
chat, image and feedback requests as a header so the app can recognize
repeat visits from the same browser. On its own it is not tied to your
name or your email.

Against that id the app keeps a record of each meme you make (which
template, when, and which surface made it), the meme image, and your 👍/👎
ratings. The record is what lets MemeGPT avoid repeating templates across
sessions and lean toward the ones you rate well, as a nudge and never a
hard rule. The text you type is not saved. It is sent to Groq, which runs
the model that picks a template and writes the captions, and to Google's
Gemini, which turns it into a search of the template library.

Lore's composer has a "Remember this group's lore" toggle, off by default.
When it is on, MemeGPT extracts short recurring names, nicknames and
running jokes from what you paste, never the whole text, so future memes
can make callbacks. Turning it off means nothing new gets extracted, and
anything already remembered stays until you erase it.

Signing in with Google turns on saved history, and saved history does
store text. Chat saves your messages as typed, with the memes they
produced. Lore saves a short summary of each moment found in a paste, or
the paste itself when it is short or can't be split into moments. For a
photo the saved text is the model's description of it. Signing in also
links the history already on that browser to the account. Each saved chat
can be deleted on its own, which removes its messages, its memes and their
stored images, the feedback on those memes, and any lore terms it
contributed.

The "Forget me" link in the header erases what the app holds for you and
clears the id from your device. Signed in, that is everything on the
account (saved chats and messages, memes and their stored images, feedback,
remembered lore) plus anything from that browser that belongs to no
account. Signed out, it is everything tied to the browser's id that
belongs to no account. History that belongs to an account can only be
erased while signed in to it, because a browser id alone does not prove
who is asking. Stored images are deleted along with their records, so
share links to those memes stop working. If the erase can't be completed
the app says so rather than reporting success, and it can be retried.

Forget me does not delete the sign-in account itself. To have that removed
as well, email support.memegpt@gmail.com.

None of this applies if `DATABASE_URL` isn't configured on the server
(e.g. local dev without Postgres). The app works identically, just without
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
- `backend/routers/me.py` — `DELETE /me`, the Forget-me endpoint.
- `backend/storage/__init__.py` — `delete_memes()`, which removes stored meme images.
- `frontend/src/lib/identity.ts` — generates/persists the anon id client-side.

Configuration lives in `backend/config.py` / `.env.example` — see
`MAX_IMAGE_BYTES`, `MAX_IMAGE_DIMENSION_PX`, `MODERATION_MODEL`,
`VISION_PROVIDER`, `VISION_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
`UPLOAD_RATE_LIMIT`, `UPLOAD_RETENTION_SECONDS`.
