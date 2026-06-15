/**
 * App Router API route for /api/chat/
 *
 * Why this exists: Next.js `rewrites()` in next.config.js buffers the entire
 * upstream response before forwarding it, which breaks SSE. App Router route
 * handlers support streaming natively — they pipe the ReadableStream directly
 * to the browser without buffering.
 *
 * The filesystem is checked before rewrites, so this route takes precedence
 * over the catch-all `/api/:path*` rewrite in next.config.js.
 */

import { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/chat/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

  // Pipe the SSE stream straight through — no buffering
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
