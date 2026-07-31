/**
 * App Router API route for /api/lore/ — the Lore surface's SSE stream
 * (Growth Phase D endpoint split). A near-exact mirror of app/api/chat/route.ts:
 * Next.js `rewrites()` buffers the whole upstream response and breaks SSE, so
 * this route handler pipes the backend's ReadableStream straight through, and
 * (per the Phase C fix) forwards the X-MemeGPT-User identity header, which the
 * generic rewrite would otherwise not carry on a hand-written proxy.
 */

import { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";
// Lore batches can be several memes long — same headroom as /api/chat/.
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  const body = await req.json();
  const anonUser = req.headers.get("x-memegpt-user");

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/lore/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(anonUser ? { "X-MemeGPT-User": anonUser } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return new Response(
      `data: ${JSON.stringify({ type: "error", message: `Backend unreachable: ${err}` })}\n\n`,
      {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
