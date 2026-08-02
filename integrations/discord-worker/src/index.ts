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
 */

import { InteractionResponseType, InteractionType, verifyKey } from "discord-interactions";

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
};

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
  await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
