# MemeGPT — "Lore" Mode (Two-Surface Restructure)

## Context

Read CLAUDE.md first. This is a frontend-led restructure with two small backend
additions. The backend batch pipeline (segmentation → sequential _stream_batch →
SSE) already supports everything Lore needs — do NOT fork or duplicate it.

Current state to fix: multi-meme UI, attach button, and count select exist only in
ChatWindow; /share is a decoupled single-meme landing page that never touches the
batch path.

## Product definition

Two public modes, one backend:

- **Chat** — a normal chatbot; the catch is it only replies in memes. Minimal
  chrome, everything automatic.
- **Lore** — for big context dumps: paste an entire group-chat history, upload
  multiple screenshots/photos, get several memes back. Explicit controls live here.
- Positioning copy (place in the UI, wording final unless improved):
  - Chat: "Talk to it like any chatbot. It only speaks meme."
  - Lore: "Drop the lore. Paste the group chat, upload the screenshots — get the
    highlight reel."

## Phase 1 — Mode toggle + Lore surface (frontend)

1. Single-page app with a **Chat | Lore** toggle (tabs) on `/`. Also expose `/lore`
   as a deep-linkable route rendering the same app with Lore active. Keep chat as
   the default tab.
2. Extract the SSE-consuming accumulator logic from ChatWindow into a shared hook
   (e.g. `useMemeStream()`) used by both surfaces. Zero behavior change for Chat.
3. **Chat surface changes:** remove the meme-count `<select>` (always "Auto").
   Keep the attach button. Nothing else changes.
4. **Lore surface:** large auto-growing textarea optimized for pasting long text;
   drag-and-drop zone + attach for up to `max_images_per_request` images with the
   existing thumbnail strip; meme-count select (Auto / 2–5); submit button labeled
   "Drop the lore".
5. **Lore results:** render as a vertical feed of meme cards (not chat bubbles).
   Each card shows the meme, its `situationText` as a small caption, and the
   existing FeedbackButtons + ShareButtons. Reuse MemeDisplay.
6. Privacy line in the Lore composer, small but visible: "Processed, never stored —
   images are deleted after your memes are generated." (Must match docs/UPLOADS.md;
   adjust wording only if the docs say something different.)

## Phase 2 — Plan event (backend, small)

In `routers/chat.py`'s `_stream_batch()`, after `resolve_contexts()` returns,
emit one SSE event before the first situation runs:

```json
{"type": "plan", "situations": ["...", "..."], "total": N}
```

- Emit it on both /chat/ and /chat/image/ streams (Chat can ignore it or show a
  compact version via ThinkingBubble; Lore renders a checklist that ticks as each
  "done" event lands, keyed by index).
- Skip the event when the fast path resolved to a single situation from a short
  message — no plan theater for one meme.
- Update the frontend SSE types in `types/index.ts` and the hook accordingly.
- Add a test asserting the event's presence for a multi-situation request and its
  absence on the fast path.

## Phase 3 — Share-target rewiring (PWA)

1. Update `manifest.json` share_target to accept shared **files** (images) and
   text: `method: "POST"`, `enctype: "multipart/form-data"`, with `files` +
   `text`/`title` params.
2. The `/share` route becomes the intake: stash the shared payload (route handler
   or service worker as required by the share_target spec) and redirect into the
   Lore composer with images pre-attached and any shared text pre-filled. The user
   reviews and submits — do NOT auto-submit shared content.
3. The old decoupled single-meme display on /share is retired; if anything links
   to it for viewing a generated meme, keep that view reachable at a distinct path.
4. Verify the flow on Android Chrome (primary share-target platform) and document
   iOS limitations in CLAUDE.md rather than fighting them.

## Phase 4 — Dump size guard (backend + frontend, small)

1. New setting `max_dump_chars` (default 20000) in config.py. Server-side clamp in
   both chat routes before segmentation; log a debug-level note when clamping.
2. Client-side: show a friendly notice in Lore when pasted text exceeds the cap
   ("Long lore! Using the first ~20k characters."). Never hard-reject text for
   length.

## Explicitly out of scope / do not do

- No new backend pipeline, no parallel generation, no changes to segmentation
  policy, caps (memes 5, images 6), or the canvas keyword-inference default.
- Do not remove any capability from the /chat/ API contract — Chat's simplification
  is UI-only.
- OPTIONAL STRETCH (skip if any friction): a "use my photos as the memes" toggle
  in the Lore composer mapping to the existing `mode=canvas` form field. Note:
  CLAUDE.md currently records a deliberate decision that this toggle is premature —
  if implemented, update that note; if skipped, say so in the plan and move on.

## Process

- Plan first (files to touch per phase); wait for approval before code.
- One phase per commit set; regression test for the text-only /chat/ flow must
  stay green throughout.
- Update CLAUDE.md: the Chat/Lore naming map (public "Lore" ↔ internal
  segmentation/batch machinery; internal "canvas" naming untouched), the new plan
  event, share-target behavior, and `max_dump_chars`.

## Definition of done

- Toggle between Chat and Lore on `/`; `/lore` deep-links to Lore.
- Chat: no count select; text-only regression test passes; behavior otherwise
  unchanged.
- Lore: pasting a ~5k-char fake chat log yields a plan event and 2+ memes rendered
  as a feed with situation captions; count select works; privacy line visible.
- Sharing 3 images via the OS share sheet lands in the Lore composer pre-attached
  (Android Chrome), and nothing auto-submits.
- Oversized paste is clamped with the friendly notice, not rejected.
- CLAUDE.md reflects all of it.
