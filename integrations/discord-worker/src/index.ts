/**
 * Growth Phase G — the Discord-facing half of the /meme slash command.
 *
 * This Worker is what Discord's Interactions Endpoint URL actually points
 * at (not the backend) — Discord requires ed25519 signature verification
 * on every request, including its PING handshake, AND a response within
 * 3 seconds. Render's free tier can cold-start in ~30s, so the backend
 * structurally cannot be the thing Discord talks to directly. This Worker
 * runs at Cloudflare's edge (always warm), verifies the signature itself
 * (the real security boundary for this whole feature), acks within the
 * 3s deadline with a deferred response, then in the background forwards
 * the actual text to the backend and PATCHes Discord's follow-up webhook
 * once a meme URL comes back.
 *
 * The backend (backend/routers/discord.py) never talks to Discord's API
 * and never sees DISCORD_PUBLIC_KEY or an interaction token — its only
 * auth is DISCORD_WORKER_SHARED_SECRET, a plain internal secret between
 * this Worker and the backend, unrelated to Discord's own protocol.
 *
 * The Worker also keeps the backend awake during the day. Render's free
 * tier stops a service after 15 idle minutes and the next visitor waits
 * about a minute for it to start, so a Cron Trigger (wrangler.toml) asks
 * for /health every 5 minutes between 8 AM and midnight Eastern. It stays
 * quiet overnight: almost nobody visits then, and Render's free tier is
 * not meant to be kept running around the clock.
 *
 * A second Cron Trigger asks for /health/db three times a day. Supabase's
 * free tier pauses a project after a week without database activity, and
 * /health never queries the database, so the 5-minute ping alone does not
 * count. It runs at 13:00, 17:00 and 21:00 UTC (morning, midday and
 * afternoon Eastern), all inside waking hours, so the 5-minute ping has
 * the backend awake already.
 */

import { InteractionResponseType, InteractionType, verifyKey } from "discord-interactions";
import { isWakingHour } from "./wakingHours.ts";

export interface Env {
  BACKEND_URL: string;
  DISCORD_PUBLIC_KEY: string;
  DISCORD_WORKER_SHARED_SECRET: string;
  // Optional override, string because wrangler vars are always strings —
  // only meant for local testing (verify_local.mjs) to exercise the
  // timeout path without a real 22s wait; unset in production.
  BACKEND_TIMEOUT_MS?: string;
}

interface DiscordInteractionOption {
  name: string;
  value: unknown;
}

interface DiscordInteraction {
  type: number;
  token: string;
  application_id: string;
  data?: {
    name: string;
    options?: DiscordInteractionOption[];
  };
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Expected POST", { status: 405 });
    }

    const signature = request.headers.get("X-Signature-Ed25519");
    const timestamp = request.headers.get("X-Signature-Timestamp");
    const rawBody = await request.text();

    if (!signature || !timestamp) {
      console.log("Rejected: missing signature headers", {
        hasSignature: !!signature,
        hasTimestamp: !!timestamp,
      });
      return new Response("Missing signature headers", { status: 401 });
    }

    // Never logs the key itself (it's not secret, but no reason to print
    // it) — length + first/last 4 chars is enough to catch a truncated or
    // whitespace-padded paste into `wrangler secret put`, the most common
    // real cause of "verified: false" on an otherwise-correct setup.
    const key = env.DISCORD_PUBLIC_KEY ?? "";
    console.log("DISCORD_PUBLIC_KEY sanity check", {
      length: key.length,
      preview: key.length > 8 ? `${key.slice(0, 4)}...${key.slice(-4)}` : "(too short)",
    });

    const isValid = await verifyKey(rawBody, signature, timestamp, env.DISCORD_PUBLIC_KEY);
    console.log("Signature verification result:", isValid);
    if (!isValid) {
      return new Response("Invalid request signature", { status: 401 });
    }

    const interaction = JSON.parse(rawBody) as DiscordInteraction;
    console.log("Interaction type:", interaction.type, interaction.data?.name ?? "(no command name)");

    if (interaction.type === InteractionType.PING) {
      // What lets the Discord Developer Portal accept this URL when saved
      // as the Interactions Endpoint URL — it PINGs live before allowing it.
      return new Response(JSON.stringify({ type: InteractionResponseType.PONG }), {
        headers: JSON_HEADERS,
      });
    }

    if (interaction.type === InteractionType.APPLICATION_COMMAND && interaction.data?.name === "meme") {
      const textOption = interaction.data.options?.find((opt) => opt.name === "text");
      const text = typeof textOption?.value === "string" ? textOption.value : "";

      // Runs after this fetch() handler returns the deferred ack below —
      // Discord's 3s clock is already satisfied at that point, so this can
      // take however long the backend (including a cold Render instance)
      // actually needs.
      ctx.waitUntil(handleMemeCommand(interaction, text, env));

      return new Response(
        JSON.stringify({ type: InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE }),
        { headers: JSON_HEADERS },
      );
    }

    return new Response("Unhandled interaction type", { status: 400 });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (controller.cron === DATABASE_CRON) {
      ctx.waitUntil(pingBackend(env, "/health/db", "Database ping"));
      return;
    }
    if (controller.cron !== KEEP_AWAKE_CRON) {
      console.log("Unknown cron, nothing run", { cron: controller.cron });
      return;
    }
    if (!isWakingHour(new Date(controller.scheduledTime))) {
      return;
    }
    ctx.waitUntil(pingBackend(env, "/health", "Keep-awake ping"));
  },
};

// Must match wrangler.toml's crons exactly: controller.cron is the string
// from there. test/scheduled.test.mjs checks that they agree.
export const KEEP_AWAKE_CRON = "*/5 0-4,12-23 * * *";
export const DATABASE_CRON = "0 13,17,21 * * *";

// A sleeping backend takes about a minute to answer, so this waits longer
// than that. The request wakes it whether or not the answer is read.
const PING_TIMEOUT_MS = 90_000;

async function pingBackend(env: Env, path: string, label: string): Promise<void> {
  const started = Date.now();
  try {
    const resp = await fetch(`${env.BACKEND_URL.replace(/\/$/, "")}${path}`, {
      signal: AbortSignal.timeout(PING_TIMEOUT_MS),
    });
    console.log(label, { status: resp.status, ms: Date.now() - started });
  } catch (err) {
    console.log(`${label} failed`, {
      error: err instanceof Error ? err.message : String(err),
      ms: Date.now() - started,
    });
  }
}

async function handleMemeCommand(interaction: DiscordInteraction, text: string, env: Env): Promise<void> {
  const followupUrl =
    `https://discord.com/api/v10/webhooks/${interaction.application_id}/${interaction.token}/messages/@original`;

  if (!text.trim()) {
    await patchFollowup(followupUrl, {
      content: "Give me something to turn into a meme — e.g. `/meme waiting for the build to finish`.",
    });
    return;
  }

  // ctx.waitUntil() is hard-capped at 30s after the response is sent
  // (every Cloudflare plan, not just Free) — if the backend fetch alone
  // (worse on a cold Render instance, which can take ~30s just to wake up)
  // ran past that, Cloudflare kills this whole background task with no
  // PATCH ever sent, leaving Discord's "thinking..." placeholder stuck
  // forever with no explanation. Racing against a 22s internal timeout
  // (leaving a few seconds of budget for the PATCH call itself) means the
  // user always gets SOME follow-up instead of silence, even when the
  // backend genuinely can't finish in time.
  const TIMEOUT_MS = env.BACKEND_TIMEOUT_MS ? Number(env.BACKEND_TIMEOUT_MS) : 22_000;

  try {
    const backendUrl = env.BACKEND_URL.replace(/\/$/, "");
    const backendResp = await Promise.race([
      fetch(`${backendUrl}/discord/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Discord-Worker-Secret": env.DISCORD_WORKER_SHARED_SECRET,
        },
        body: JSON.stringify({ text }),
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("backend-timeout")), TIMEOUT_MS),
      ),
    ]);

    if (!backendResp.ok) {
      const bodyText = await backendResp.text().catch(() => "(couldn't read body)");
      console.log("Backend returned non-OK status", { status: backendResp.status, body: bodyText });
      await patchFollowup(followupUrl, {
        content: "Couldn't generate a meme for that one — try again in a bit.",
      });
      return;
    }

    const { meme_url: memeUrl } = (await backendResp.json()) as { meme_url: string; template_id?: string };
    // Local-disk storage returns a backend-relative path
    // (/static/generated/<id>.png); R2 storage already returns an absolute
    // URL. Same normalization frontend/src/lib/api.ts's memeImageUrl()
    // already does for exactly this reason.
    const absoluteUrl = memeUrl.startsWith("http") ? memeUrl : `${backendUrl}${memeUrl}`;
    console.log("Generated meme URL:", absoluteUrl);

    await patchFollowup(followupUrl, {
      embeds: [{ image: { url: absoluteUrl } }],
    });
  } catch (err) {
    const timedOut = err instanceof Error && err.message === "backend-timeout";
    await patchFollowup(followupUrl, {
      content: timedOut
        ? "That's taking longer than expected (probably a cold backend) — try again in a moment, it should be faster the second time."
        : "Something went wrong generating that meme.",
    });
  }
}

async function patchFollowup(url: string, body: Record<string, unknown>): Promise<void> {
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "(couldn't read body)");
    console.log("Discord follow-up PATCH failed", { status: resp.status, body: text });
  }
}
