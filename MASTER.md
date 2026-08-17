# MemeGPT — Design System (MASTER)

Canonical source of truth for the frontend rebuild's visual identity. Every
color, size, radius, shadow, and motion value used in `frontend/src` must
trace back to a token defined here — no rogue hex values, no magic numbers.

Supersedes the Phase 0-2 monochrome-dark token set only where noted below.
Most of Phase 0-2 actually survives — the accent hue, the dark shell, the
Anton wordmark, the `.caption` treatment — the rebuild is about polish and
composition, not a different genre.

---

## 0. Pivot — read this before the rest

The first version of this document (still visible in git history) specified
a full flip to a cream/paper theme with torn-edge "pinned" cards, tape,
stamps, and poster-scale Anton — a zine/collage direction. It was validated
through three live Artifact gates (mood-direction comparison, a synthesis
specimen, a full token/component sheet) and got real sign-off each time.

**It failed in the actual running app.** Real-browser review (not another
mockup) called it "still basic," on top of which it turned out two
Artifact-only validation cycles were compounding a blind spot: Artifacts
looked right in isolation but never matched what real deployed code does,
compounded by two actual bugs that were live at the same time (`.env.local`
had blanked `NEXT_PUBLIC_API_BASE`/`BACKEND_URL`, so the backend was
genuinely unreachable during part of that review; the header wordmark's
stroke was miscalibrated for its size). Both are fixed now, but the paper
direction itself was also a real miss, independent of those bugs — it read
as a craft-project genre swap rather than a considered evolution.

**The correction, grounded in real reference work, not more freehand
guessing:** screenshotted 21st.dev's "AI Chat" component category (116 real
components from working design engineers) and Aceternity UI, then pulled
actual source from Vercel's own `ai-chatbot` template (20.8k stars, same
Next.js/Tailwind/shadcn stack) to ground structure and motion in something
proven rather than invented. Findings:

- Well-regarded AI chat products stay **dark**. None of the good examples
  use paper/craft texture. Distinctiveness comes from **motion and depth
  polish** on a clean surface, not decorative genre.
- Suggestion/prompt UI reads as substantial when laid out as a **grid**
  (Vercel's `suggested-actions.tsx` uses `sm:grid-cols-2`), not a thin
  centered vertical stack — the stack was a real, fixable cause of the
  "zoomed out" / dead-space complaint.
- Motion needs to be **staggered per-element** (`delay: 0.06 * index` in
  the reference) to actually register as "transitions." A single container
  fading in once is invisible in practice.

So: **the shell stays dark.** §1 onward below describes what's actually
implemented now — the old ink-0/1/2 tokens (never removed from
`globals.css`) are back in use, plus real additions for depth and motion.
The cream/paper tokens (`--cream*`, `--ink-warm*`, `--tape-material`) are
still defined in `globals.css` but unused — harmless dead code for now,
worth deleting once nothing references them.

---

## 1. Color

Unchanged from Phase 0-2, this was never the problem:

| Token | Hex | Role |
|---|---|---|
| `--ink-0` | `#0A0A0B` | Page background |
| `--ink-1` | `#141416` | Raised surface (cards, sidebar) |
| `--ink-2` | `#1E1E21` | Input, hover state |
| `--line` | `#2A2A2F` | Hairline borders |
| `--paper` | `#FAFAF7` | Primary text |
| `--paper-dim` | `#8E8E94` | Secondary text |
| `--accent-color` | `#FF4D1C` | The one hue — interactive state only |

No second hue, no gradients, no glow/neon (`frontend-tokens` skill's own
non-negotiable). Depth comes from neutral `box-shadow` (black-based, not
colored bloom) — see §5.

---

## 2. Typography

- **Anton** (`--font-display`) — the wordmark and empty-state headlines,
  used **restrained**, not poster-dominating. `.headline-poster` now
  renders at `--text-display` (`clamp(28px, 3.5vw, 40px)`), not the old
  76px `--text-poster` scale — the poster-scale version read as
  page-dominating decoration rather than a considered statement.
- **`.caption-mark`** (new) — pairs with `.caption` at logo/wordmark scale
  (`text-xl` and below) to thin the stroke from `.caption`'s default
  `0.08em` down to `0.03em`. `.caption`'s stroke is tuned for actual
  meme-image captions rendered 40px+; at wordmark size that same
  proportional stroke ate into Anton's letterforms enough to look
  chunky/blobby (real bug, reported as "the memegpt logo looks weird" and
  fixed). Applied everywhere `.caption` appears below ~24px: `ModeTabs.tsx`,
  `LandingPage.tsx`'s header logo, `m/[id]/page.tsx`'s share-page logo.
  `.caption` alone (no `-mark`) stays correct for LandingPage's large hero
  use (`text-4xl`/`text-6xl`) — plenty of counter space to absorb the full
  stroke at that size.
- **System sans** (Geist) — unchanged, anything typed or read closely.

---

## 3. Composition — the actual fix for "zoomed out"

Not a token, a rule: **don't center a small content cluster in a large
empty flex container.** Chat's empty state was originally
`items-center justify-center h-full` — on a real monitor this reads as
small/adrift regardless of what's inside it, which is most of what "the
whole chat seems zoomed out" was pointing at.

Current pattern (`ChatWindow.tsx`'s empty state):
- Content anchored via `pt-[12vh]`, not vertically centered — gives it a
  fixed position to sit against instead of floating in the middle of
  however tall the viewport happens to be.
- Suggestion chips in a `grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl` —
  real width, real density, modeled directly on Vercel's
  `suggested-actions.tsx` structure (mechanics copied, values re-expressed
  in our tokens per `frontend-tokens`' sourcing rule).

---

## 4. Radii

Back to Phase 0-2's language — `rounded-xl`/`rounded-2xl` for
cards/bubbles/inputs, `rounded-lg` for smaller controls. The "no more
pills" instinct from the paper direction is **not** carried forward as a
blanket rule; Vercel's own reference uses `rounded-xl` throughout and it
reads as considered, not generic — radius was never the actual problem.

---

## 5. Shadow & motion

Neutral depth, not colored glow — `frontend-tokens`' non-negotiable:

```css
--duration-fast: 150ms;      /* hover, focus, border/color shifts */
--duration-settle: 280ms;    /* — */
--duration-arrive: 320ms;    /* per-element entrance animation length */
--ease-settle: cubic-bezier(0.16, 1, 0.3, 1);
```

- `.prompt-chip` — `--ink-1` fill, `--line` border, `box-shadow: 0 1px 2px
  rgba(0,0,0,.3)` at rest; hover adds `translateY(-2px)`, border →
  `--accent-color`, fill → `--ink-2`, shadow grows to `0 6px 16px
  rgba(0,0,0,.45)`. Focus-visible gets a real ring (`box-shadow: 0 0 0 2px
  ink-0, 0 0 0 4px accent`), same pattern shadcn's own `button.tsx` already
  uses elsewhere in this codebase — not a novel pattern.
- `.arrive-settle` / `@keyframes settleIn` — `opacity 0→1` +
  `translateY(10px)→0` + `scale(.98)→1`. No rotation (that was the
  corkboard metaphor, dropped with the paper direction).
- **Staggered entrance is required, not optional**, for any group of
  elements arriving together (chips, list items) — apply
  `.arrive-settle` per item with an inline `animationDelay` offset
  (`${base + i * 60}ms`), `animationFillMode: "backwards"` so items don't
  flash visible before their delay starts. A single fade on the wrapping
  container is not motion that registers.
- `.thinking-orb` / `@keyframes breathe` — replaces the old 3-dot bounce.
  One 10px circle, `--accent-color` fill, `scale(.85→1)` +
  `opacity(.55→1)` on a 1.6s loop. Motion only, no colored blur — this is
  the "glowing orb" idea from the 21st.dev research, kept but de-glowed to
  respect the non-negotiable.

All motion respects `prefers-reduced-motion: reduce` (animations disabled
outright, not just shortened).

---

## 6. What this does NOT change

- The single-accent-hue rule.
- Anton for display, system sans for anything typed/read closely.
- All copy voice, backend behavior, routing, the `.caption` meme-text
  treatment in `compose_meme()`.
- No `LLM_PROVIDER`, backend, or routing changes. Visual layer only.

---

## 7. Rollout order

Page by page, validated at each step:

1. ✅ Chat (`ChatWindow.tsx`) — empty state, composer, thinking indicator.
   Verified in real Chromium + WebKit + actual Safari (screen-captured
   directly, not simulated) after the paper-direction reversal.
2. ✅ `MemeCard.tsx` — hover lift (border/shadow/translateY), same
   `--duration-settle` timing as everything else. Verified against two
   real live-generated memes.
3. ✅ Lore (`LoreView.tsx`) — composer depth + focus-within ring, two
   literal-hex spots fixed to real tokens, staggered `.arrive-settle` on
   feed entries (capped stagger) — this is where it matters most, since
   one submission routinely lands several memes at once. Verified with a
   real "Change My Mind" meme.
4. ✅ Arc (`ArcView.tsx`) — lightest touch as planned: just added
   `.arrive-settle` to the three card surfaces (empty state, story card,
   share screen) for consistency. Nothing else changed — it was already
   the best-built of the three.
5. **Next.** `ModeTabs.tsx` / header chrome, `Avatar.tsx`, `AuthControl.tsx`
   — last, once the primary surfaces prove the system holds up.

Each step gets real-browser verification (driver screenshots across
engines, plus an actual Safari screen-capture when feasible) before moving
to the next — Artifact-only validation is not sufficient on its own,
per §0.

---

## 8. Motion/interaction polish pass (post-rollout)

Once the §7 rollout landed, a second pass added real interaction mechanics
sourced from external research (5 parallel agents surveying reactbits.dev,
motion.dev, bklit.com, kokonutui.com — full findings not duplicated here,
see conversation history) — copying MECHANICS only, never aesthetics, per
`frontend-tokens`' sourcing rule. All zero-new-dependency (`motion`,
already installed, covers everything below):

- **`MessageBubble.tsx`'s multi-meme carousel** — real spring-physics drag
  (`useMotionValue` + imperative `animate()`, NOT the declarative `animate`
  prop, which conflicts with a live drag gesture on the same value — a
  real bug hit and fixed mid-implementation) replacing raw CSS scroll-snap,
  plus a `layoutId`-based dot indicator that slides between positions.
  Also fixed a real layout bug found via this work: the card was sized to
  the *tallest* slide always (a flex-row's natural height default), not
  the active one — now tracks and animates to the active slide's real
  height. **Caveat**: automated verification (Playwright mouse simulation
  and manually-dispatched real `PointerEvent`s) could not trigger Motion's
  drag recognizer — a known friction point between synthetic/untrusted
  events and pointer-based drag libraries. Dot-navigation, the layoutId
  indicator, and the height fix are fully verified; the raw swipe gesture
  itself is not personally confirmed working, though it's a standard,
  widely-used production Motion pattern.
- **`AnimatePresence`/`popLayout`** on pending-photo removal (`ChatWindow.tsx`,
  `LoreView.tsx`) — the app previously had zero exit animations anywhere.
- **Odometer digit-roll** (`ArcView.tsx`) — `OdometerNumber`/`OdometerDigit`,
  em-based per-digit sliding columns, applied only to genuinely numeric
  stats (total memes, streak days, aura score) via a new optional
  `numeric` field on the stat step type — left free-form stats (time
  labels, template names) as plain text.
- **Real drag-state visual** on Lore's drop zone — a centered overlay
  ("Drop to add screenshots") replacing a bare border-color change, border
  also switches dashed→solid on drag-enter.
- **3D card-flip** on `MemeCard.tsx`'s image (pure CSS
  `[transform-style:preserve-3d]`, no JS) — hovering reveals which
  template was used, prettified via a new shared `templateLabel()` in
  `lib/utils.ts` (also de-duplicated `LandingPage.tsx`'s local copy of the
  same function). New optional `templateId` prop, threaded through from
  `MessageBubble.tsx` and `LoreView.tsx` (both have it on live-streamed
  memes); not available on hydrated/persisted history since the backend
  doesn't return `template_id` from `GET /conversations/{id}/messages` —
  degrades to the plain non-flip card there, not a bug.
- **Dim-siblings-on-hover** on Lore's feed (`hoveredIndex` state) — hovering
  one card in a multi-meme batch dims the others without hiding them.
- **`DecryptedText.tsx`** (new component) — character-scramble-to-resolve,
  pure `useState`/`useEffect`, respects `prefers-reduced-motion`. Applied
  to plain-text assistant replies in both `MessageBubble.tsx` and
  `LoreView.tsx` (the graceful-degrade path when a meme can't be made —
  the one place real generated text lands outside a baked-in meme image).

- **Pointer-tracked highlight** on `.prompt-chip` (reactbits' Specular
  Button mechanic) — a sharp-edged radial tint (`radial-gradient(120px
  circle at var(--mx,50%) var(--my,50%), ...)`, not a blurred glow) that
  follows the cursor. `--mx`/`--my` are set via direct DOM mutation in the
  `onMouseMove` handler (`e.currentTarget.style.setProperty`), not React
  state — a handler firing dozens of times a second has no business
  triggering a re-render. Verified the CSS vars update and the highlight
  visibly moves left→right with the cursor.

All 8 of the original 9 batch items are done.

## 9. Dependency-gated additions

Three findings needed a new dependency — user explicitly approved all
three by name before anything was installed:

- **`charts/gauge.tsx`** — bklit's Gauge, pulled via the actual shadcn
  registry command (`npx shadcn@latest add @bklit/gauge-chart`), not a
  guessed npm install. Real dependency turned out to be `d3-shape` +
  `@visx/responsive`/`@visx/pattern`, not `recharts` (a testimonial the
  research agent cited was wrong/outdated) — `recharts` was installed
  speculatively first, confirmed unused, then removed. Wired into
  `ArcFinaleSlide` replacing the old plain "+2,847 / AURA FARMED" text —
  `value` (0–100 fill) is `aura / 20_000`, mirroring
  `backend/arc/copy.py`'s `_TIER_THRESHOLDS` top tier ("aura farming god"
  is uncapped past it) via a new `AURA_GOD_TIER_THRESHOLD` constant, so
  the gauge reads as genuine progress toward the next tier, not an
  arbitrary scale. `activeFill`/`inactiveFill` passed explicitly as our
  own tokens (the component's default reads `var(--chart-1)` etc., which
  this project never defined) rather than adding a new CSS-variable
  layer. **Real bug found and fixed**: my first debug harness rendered
  the Gauge with mock data available synchronously at the top level,
  producing a floating-point SSR/CSR hydration mismatch in the SVG path
  strings (Node's and the browser's trig functions differ in the last
  couple of decimal digits) — the *real* `ArcView.tsx` never actually
  hits this, since `stats` starts `null` and is only set client-side
  inside a `useEffect`, so the Gauge is never part of the initial SSR
  payload in production. Fixed the debug harness to match that real
  async pattern rather than patching around a bug that doesn't exist in
  production.
- **`reveals/PixelRevealImage.tsx`** (shipped) vs. a WebGL halftone
  reveal (`ogl`, built, compared live, not shipped) — both targeted the
  same meme-reveal moment in `MemeDisplay.tsx`, so only one could win.
  Built both behind a real side-by-side comparison route (not decided
  blind), user picked the pixel-grid crossfade. The halftone version had
  a real shader bug caught during that comparison — the auto-reveal and
  cursor-hover reveal shared one `uMouse`/`uRadius` uniform pair, so with
  no cursor present the "auto-reveal circle" was centered on the parked
  off-screen mouse position instead of the canvas center — fixed by
  splitting into two independent reveal circles combined via `max()` in
  the shader, but moot once GSAP won; `ogl` was uninstalled and the
  halftone component deleted rather than left as dead code.
  `PixelRevealImage` replaced `MemeDisplay.tsx`'s plain `next/image` with
  a plain `<img>` + an absolutely-positioned grid of cells GSAP-staggers
  from opaque to transparent (`stagger: { each: 0.012, from: "random" }`)
  — `object-contain` preserved exactly (never `object-cover`: memes have
  wildly variable aspect ratios and cropping one can cut off the caption
  or the joke itself). Verified end-to-end against three real
  live-generated memes across all three consumer contexts (Chat
  single-meme, Chat's multi-meme carousel, Lore's feed) — zero console
  errors, no cropping regression.

---

## 10. Phase 4 — surfacing unused backend features

Two backend endpoints existed fully built, with typed frontend API helpers
already written in `lib/api.ts` (`generateMeme()`, `explainMeme()`), never
called from any UI. Research-first, per the roadmap: read both routers,
confirmed via grep that neither call site existed anywhere, then reported
back with concrete scope before writing any code.

**`/explain/` enrichment** — `ExplainResponse` gained `image_url` and
`text_boxes` (a new `TextBoxInfo` model: label + description per caption
field). `image_processing/compositor.py` gained a public
`template_image_url()` — this consolidates `arc/copy.py`'s private
`_template_image_url` (Growth Phase D's "signature template" thumbnail),
which now imports the shared version instead of duplicating it, since
Phase 4 gave it a second real consumer. `vector_db/chroma_client.py`
gained `list_all_template_records()` — one bulk `col.get()` call instead
of N individual `get_template_record()` calls. New `GET /explain/` lists
every template (121 in the live collection); the existing `POST /explain/`
now also returns `image_url`/`text_boxes`. `MemeCard.tsx`'s hover-flip
(§6/§9) now shows the template's real description/tags instead of just
the prettified name.

**`/generate/` — the manual meme maker ("Make"), a genuinely new 4th
product surface**, not a small enhancement — placement (new nav tab vs.
an entry point inside Chat/Lore) was a real product decision, asked
explicitly rather than assumed; user picked a full 4th `ModeTabs` tab.
New `app/make/page.tsx` (standalone, no sidebar — same tier as Arc, since
there's no conversation/history concept here) + `MakeView.tsx`: a
searchable grid of all 121 templates (`GET /explain/`), a dynamic caption
form built from the selected template's real `text_boxes` (field labels
and placeholders come from the actual per-template config, not a generic
top/bottom guess), `POST /generate/`, result shown via the existing
`MemeCard`.

**Three real, non-obvious bugs found and fixed while wiring this up, all
confirmed via direct testing, not assumed fixed:**

1. **`/api/generate/` and `/api/explain/` had no working path at all.**
   `lib/api.ts`'s `BASE = "/api"` routes through Next.js, and every
   endpoint actually exercised before now (`chat`, `lore`, `feedback`) has
   its own hand-written `route.ts` — `next.config.js`'s generic
   `/api/:path*` rewrite 308-redirects POST requests to trailing-slash
   paths (Next's own slash-normalization firing before the rewrite runs),
   which is *why* those hand-written routes exist, not an accident. Since
   `/generate/`/`/explain/` were never called, this was never hit before.
   Added `app/api/generate/route.ts` and `app/api/explain/route.ts`
   (GET + POST) matching the proven pattern. Confirmed via direct `fetch()`
   in a live page context that browsers *do* correctly follow the 308 with
   the POST body intact — so the rewrite alone might have technically
   worked — but matching the established, working convention rather than
   depending on redirect-follow behavior is the right call regardless.
2. **`MemeCard`'s hover-flip could show its back face by default.** Make's
   "Generate" button and the result card that replaces it can land at
   overlapping screen coordinates — a cursor resting from the click reads
   as an immediate hover on the new card. Confirmed two dead ends before
   the real fix: gating behind a timed `pointer-events: none` didn't work
   (CSS `:hover` re-evaluates the instant pointer-events re-enables,
   cursor movement or not); switching from CSS `group-hover` to a plain
   JS `onMouseEnter` handler *also* didn't work (Chromium fires a genuine
   `mouseenter` when the DOM mutates under a stationary cursor — a new
   element appearing where an old one was reads as the pointer "entering"
   it, zero physical movement required). Real fix: a module-level
   `mousemove` listener tracks the live cursor position continuously;
   each card records that position once at mount, and `onMouseEnter` only
   flips if the live position has since moved a real distance (>4px) from
   the mount-time reading — a synthetic mouseenter from a DOM mutation
   reports the exact same coordinates and gets correctly ignored. Verified
   both directions live: stationary cursor after "Generate" now correctly
   shows the front face; a genuine, clearly-separated hover (20,20) →
   (450,280) still flips it. Re-verified Chat's existing flip usage
   afterward to confirm the rewrite didn't regress it.
3. **Backend dev server was running stale code.** After the `explain.py`/
   `chroma_client.py`/`compositor.py`/`arc/copy.py` edits, `GET /explain/`
   returned `405 Method Not Allowed` — the long-running `uvicorn --reload`
   process (up since early in this session) hadn't picked up the changes.
   Restarted clean with the same credential-scoping pattern used all
   session (DB/Supabase real, R2/Gemini/Discord/Anthropic blanked).

Verified: all 235 backend tests pass (zero regressions from the
`compositor.py`/`arc/copy.py` consolidation or the new endpoints), zero
console errors across all five pages including `/make`, a real generated
meme end-to-end through the manual maker with real captions
("MY CODE IN PRODUCTION" / "MY CODE IN THE PR REVIEW" on Woman Yelling At
Cat).

---

## 11. Phase 5 — library/Arc polish (MAINTENANCE_MODE deliberately excluded)

"Library" is `ConversationSidebar.tsx` — the closest thing to a history/
library of past content in the app (past conversations, each with a real
meme thumbnail). Arc already got its motion pass in §7/§9 (arrive-settle,
the Gauge) — this section is the sidebar catching up to the same bar.

- Staggered `.arrive-settle`-equivalent entrance (`AnimatePresence` +
  `motion.div` with a capped per-index delay) on the conversation list —
  matches Chat's chips, Lore's feed, Arc's cards, none of which this list
  had.
- Real exit animation on delete (`AnimatePresence mode="popLayout"`) —
  same category of gap as the pending-photo-removal fix in Chat/Lore:
  deleting a conversation previously just refetched and hard-cut the
  removed row.
- "+ New chat" gained the same hover-lift (translateY + shadow) used on
  every other button in the app; it was still plain `transition-colors`.

**Verification gap, disclosed rather than glossed over**: this needs a
real signed-in session with real conversations to see rendered at all
(`ConversationSidebar` returns `null` when signed out) — same limitation
as Phase 2's original build ("no way to complete a real Supabase sign-in
from here"). Confirmed clean: `tsc`, a full production build (`/make`,
`/api/generate`, `/api/explain` all correctly in the route manifest), and
zero console errors across all five pages signed-out. The actual
sidebar-with-real-data appearance is NOT independently verified — flagged
to the user to check for real.

**MAINTENANCE_MODE explicitly not touched** — a real production
visibility change, needs its own separate go-ahead per the project's own
established rule, not something "next"/"continue" should imply.
