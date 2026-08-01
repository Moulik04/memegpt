# Discord `/meme` Setup — Deploy Runbook

Growth master-prompt Phase G, Discord half. Everything up to this point
(backend endpoint, Cloudflare Worker source, local verification) is done
and pushed. Everything below is the handoff — steps only you can do,
since they touch your Discord app, your Cloudflare account, and your
Render deployment.

## 1. Deploy the backend change

Nothing new to configure here beyond what's already in the code — the new
`/discord/generate` endpoint ships disabled-by-default (it 503s until
`DISCORD_WORKER_SHARED_SECRET` is set). Once you're ready:

1. In Render's dashboard, add an env var: `DISCORD_WORKER_SHARED_SECRET` —
   any long random string you generate yourself (e.g.
   `openssl rand -hex 32`). This is **not** a Discord credential — it's a
   private secret only the Worker and the backend need to agree on, so
   the `/discord/generate` endpoint can't be hit by a random public caller.
2. Redeploy the backend (or just save the env var if Render auto-deploys
   on env var changes).

You do **not** need to set `DISCORD_APP_ID`, `DISCORD_PUBLIC_KEY`, or
`DISCORD_BOT_TOKEN` on Render — the backend never talks to Discord's API
directly (see `routers/discord.py`'s module docstring for why), so it has
no use for them. Keeping them in your local `backend/.env` is fine and
harmless (`config.py` recognizes the fields either way) but not required
for production.

## 2. Deploy the Cloudflare Worker

```bash
cd integrations/discord-worker
npm install
wrangler login          # opens a browser to authorize the CLI against your account
```

Edit `wrangler.toml`'s `BACKEND_URL` if your Render backend's URL differs
from the placeholder already in there.

Set the two secrets (never committed, not in `wrangler.toml`):

```bash
wrangler secret put DISCORD_PUBLIC_KEY
# paste the Public Key from the Discord Developer Portal's
# General Information page when prompted

wrangler secret put DISCORD_WORKER_SHARED_SECRET
# paste the SAME random string you set on Render in step 1
```

Deploy:

```bash
wrangler deploy
```

This prints the Worker's live URL, something like
`https://memegpt-discord-worker.<your-subdomain>.workers.dev`. Copy it —
you need it in the next two steps.

## 3. Register the `/meme` command (one-time)

This needs your **Bot Token** (Discord Developer Portal → your app → Bot
tab). Run this yourself — never paste the token anywhere else, including
to me:

```bash
curl -X POST "https://discord.com/api/v10/applications/<YOUR_APP_ID>/commands" \
  -H "Authorization: Bot <YOUR_BOT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "meme",
    "description": "Generate a meme from your message",
    "type": 1,
    "options": [
      {
        "type": 3,
        "name": "text",
        "description": "What should the meme be about?",
        "required": true
      }
    ]
  }'
```

A `200`/`201` response with a command object back means it registered. It
can take up to an hour to propagate globally the first time (usually much
faster in practice), per Discord's own documented behavior for global
commands.

## 4. Point Discord at the Worker (the live verification step)

Discord Developer Portal → your app → **General Information** →
**Interactions Endpoint URL** → paste the Worker URL from step 2 → **Save**.

Discord immediately sends a real signed `PING` to that URL and only
accepts the save if it gets back a valid `PONG` — this is the moment that
proves the whole chain (Worker deployed correctly, `DISCORD_PUBLIC_KEY`
set correctly) actually works. If the save fails, double-check the secret
was set on the exact Worker you deployed (`wrangler secret list` shows
what's currently set, not the values, just which names exist).

## 5. Test it for real

In the test server you already authorized the app into (via the OAuth2 URL
Generator step from earlier): type `/meme` in any channel, fill in the
`text` option, send it. You should see Discord's "thinking..." indicator
(the deferred ack) followed by the actual meme a few seconds later (longer
on a cold Render instance — that's expected and exactly what the Worker's
deferred-ack design is for).

## Troubleshooting

- **Command doesn't show up in the server**: re-check step 3 registered
  successfully, and that the app was actually authorized to that server
  with the `applications.commands` scope (the OAuth2 URL Generator step).
- **"This interaction failed"**: usually means the Worker responded with
  something other than a valid deferred ack, or Discord's initial PING
  verification never succeeded — check `wrangler tail` (streams live logs
  from your deployed Worker) while testing.
- **Deferred, but never gets a real follow-up**: the backend call or the
  follow-up PATCH failed — `wrangler tail` will show the Worker's own
  console output/errors from the `ctx.waitUntil()` background task.
- **Local Worker logic changes needed later**: `node
  integrations/discord-worker/verify_local.mjs` re-runs the full local
  verification (PING/PONG, signature rejection, deferred-ack shape,
  background-forward correctness) against your changes before you
  `wrangler deploy` again — no live Discord or Cloudflare traffic involved.
