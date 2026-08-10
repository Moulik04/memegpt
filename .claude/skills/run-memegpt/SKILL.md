---
name: run-memegpt
description: Build, launch, and drive the real running MemeGPT app (backend + frontend) — use when asked to run memegpt, start the dev servers, take a screenshot of the chat UI, or verify a change against the actual live app rather than tests.
---

Paths below are relative to the repo root (`memegpt/`), not this skill
directory. The driver is `.claude/skills/run-memegpt/driver.mjs` — a
Playwright script, isolated from the app's own `frontend/node_modules`
(its own `package.json` lives next to it in this skill directory).

MemeGPT is one app with two processes: a FastAPI backend
(`backend/`, port 8000) and a Next.js frontend (`frontend/`, port 3000)
that talks to it. Both must be running to drive the real chat UI; the
backend alone is enough for the direct API path.

## Prerequisites

- Backend: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` (already set up in this repo's `backend/.venv`).
- Frontend: `cd frontend && npm install` (already set up).
- Driver: `cd .claude/skills/run-memegpt && npm install && npx playwright install chromium` — the second command downloads a real Chromium build (~270MB) if the cached version doesn't match this `playwright` package version. Confirmed live: this repo's pre-existing global Playwright cache (`~/Library/Caches/ms-playwright`) had chromium-1228 cached, but the installed `playwright@1.62.1` package needed chromium-1234 — the version mismatch is not a false alarm, the install step is real and necessary the first time.
- **The credential-guard hook (`.claude/hooks/guard_credentials.sh`) blocks any Bash command containing `python3`/`pytest`/`uvicorn` if `backend/.env` has real credentials and the command doesn't blank them.** Every command below that touches Python includes `DATABASE_URL=` inline for exactly this reason — it's not optional decoration, commands without it get blocked.

## Run (agent path)

**1. Launch the backend** — real `GROQ_API_KEY` (needed for actual meme
generation), but every credential that could write to shared/production
storage is blanked so this stays a safe local run (falls back to local
disk storage, no Postgres):

```bash
cd backend && source .venv/bin/activate
DATABASE_URL= R2_ACCOUNT_ID= R2_ACCESS_KEY_ID= R2_SECRET_ACCESS_KEY= R2_BUCKET= R2_PUBLIC_BASE_URL= \
SUPABASE_URL= SUPABASE_ANON_KEY= GEMINI_API_KEY= ANTHROPIC_API_KEY= \
DISCORD_BOT_TOKEN= DISCORD_WORKER_SHARED_SECRET= DISCORD_APP_ID= DISCORD_PUBLIC_KEY= \
LLM_PROVIDER=groq \
nohup uvicorn main:app --host 127.0.0.1 --port 8000 > /tmp/memegpt-backend.log 2>&1 &
disown
```

Wait for it, then confirm:
```bash
sleep 3 && curl -s http://127.0.0.1:8000/health
# → {"status":"ok","service":"memegpt-backend"}
```

(`GEMINI_API_KEY=` blanked too, deliberately — RAG falls back to
ChromaDB's local embedding model instead of burning the real Gemini
quota for a local smoke run. Confirmed this repo's `backend/data/chroma/`
already had seeded data from a prior real session; if you ever see a
dimension-mismatch error here, delete that directory and let it reseed.)

**2. Launch the frontend**, pointed at the local backend:

```bash
cd frontend
DATABASE_URL= BACKEND_URL=http://127.0.0.1:8000 NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 MAINTENANCE_MODE= \
nohup npm run dev > /tmp/memegpt-frontend.log 2>&1 &
disown
sleep 6 && curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:3000/chat
# → HTTP 200
```

**3. Drive it** — the real, verified path (not `npm start` and a window):

```bash
cd .claude/skills/run-memegpt
DATABASE_URL= node driver.mjs chat "when the intern pushes directly to main" /tmp/memegpt-chat-test.png
# → OK: meme rendered, screenshot saved to /tmp/memegpt-chat-test.png
```

This navigates to `/chat`, types into the real input, submits, waits (up
to 45s — a real Groq round trip through segmentation → RAG → intent
routing → Pillow compositor takes several seconds) for a meme image to
actually render in the DOM, then screenshots. Confirmed for real: the
screenshot shows a genuine "This Is Fine" 2-panel meme with real captions
("INTERN PUSHED DIRECTLY TO MAIN" / "THIS IS FINE."), the memegpt
watermark bottom-right, and working feedback buttons — not a placeholder,
not an error state.

`driver.mjs` also supports a generic screenshot command for any route:
```bash
DATABASE_URL= node driver.mjs screenshot /lore /tmp/lore.png
```

**4. Direct API path** (no browser — useful when a change is backend-only):

```bash
DATABASE_URL= curl -sN --max-time 30 -X POST http://127.0.0.1:8000/chat/ \
  -H "Content-Type: application/json" \
  -H "X-MemeGPT-User: probe" \
  -d '{"message": "me trying to explain to my parents what I do for work"}'
```
Streams real SSE events: `thinking` (analyzing → rendering) → `done`
(with `meme_url`/`template_id`) → `batch_done`. Confirmed live — a real
run picked `scientist_myself` and rendered a real PNG.

## Run (human path)

`cd backend && source .venv/bin/activate && uvicorn main:app --reload`
in one terminal, `cd frontend && npm run dev` in another, open
`http://localhost:3000/chat` in a real browser. Same servers as above,
just interactive instead of backgrounded.

## Stopping

```bash
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:3000 | xargs kill 2>/dev/null
```

## Test suite

```bash
cd backend && source .venv/bin/activate
DATABASE_URL= python -m pytest -q
# → 235 passed
```
(Or `./scripts/verify_safe.sh python -m pytest -q` from the repo root —
same effect, blanks more vars than this needs but works identically.)

## Gotchas

- **`.fill()` does not work on the chat input — confirmed, not assumed.**
  Playwright's `locator.fill("...")` set the input's DOM value, but this
  repo's `ChatWindow.tsx` input is a React controlled component
  (`value={input}` / `onChange`), and `.fill()`'s underlying event
  didn't register with React's state here: the submit button stayed
  `disabled` and the click timed out waiting for it to become enabled.
  Fix: `page.keyboard.type(message)` after a real `.click()` to focus the
  field — genuine keystrokes, which React's onChange does pick up.
- **`waitUntil: "domcontentloaded"` isn't enough before interacting.**
  The chat input exists in the DOM at that point but Next.js hydration
  (which is what wires up the controlled-input state) hasn't necessarily
  finished. `waitUntil: "networkidle"` before the first interaction
  avoided a flaky race; `domcontentloaded` alone reproduced the same
  "button never enables" symptom as the `.fill()` issue above, separately
  from it.
- **A real hydration bug exists on every fresh `/chat` load — found while
  building this driver, not induced by it.** The browser console shows a
  React hydration mismatch on every page load: "Text content did not
  match. Server: ... Client: ..." pointing at the empty-state example
  prompt chips. Root cause, traced to the actual code:
  `ChatWindow.tsx`'s `useState(() => pickRandomPrompts(6))` runs during
  both the server render and the client hydration pass, and
  `examplePrompts.ts`'s `pickRandomPrompts()` uses unseeded `Math.random()`
  — so the server picks 6 prompts, the client picks a different 6, React
  sees a text mismatch, and the whole page falls back to full
  client-side rendering. This affects the real production site on every
  visit, not just this local run — worth a real fix (seed the random
  pick deterministically, or move it into a `useEffect` so it only ever
  runs client-side), separate from this skill.
- **The credential-guard hook fires on substring match, not semantic
  intent.** A command like `... && python3 --version` gets blocked even
  though it's read-only, because the hook just checks whether `python3`
  appears anywhere in the command string. Prefix with `DATABASE_URL=`
  (or route through `./scripts/verify_safe.sh`) even for trivial
  Python-adjacent commands.
- **Playwright's browser cache can silently mismatch the installed
  package version.** `~/Library/Caches/ms-playwright` had `chromium-1228`
  from some earlier, different Playwright install; `playwright@1.62.1`
  wanted `chromium-1234` and failed with a clear "Executable doesn't
  exist" error (not a hang) pointing at the missing path — the fix really
  is just `npx playwright install chromium`, not a deeper environment
  problem.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `guard_credentials.sh` blocks a command | Prefix with `DATABASE_URL=` (matches the hook's allow-pattern) or use `./scripts/verify_safe.sh <command>` |
| `Executable doesn't exist at .../chrome-headless-shell` | `cd .claude/skills/run-memegpt && npx playwright install chromium` |
| Driver times out waiting for `.meme-reveal img` | Check `/tmp/memegpt-backend.log` — likely Groq rate-limited or `GROQ_API_KEY` isn't set in the ambient shell |
| Driver's submit button never becomes enabled | Confirms the input isn't receiving real keystrokes — check the driver is using `page.keyboard.type()`, not `.fill()` |
| Port 3000 or 8000 already in use | `lsof -ti:PORT \| xargs kill` before relaunching |
