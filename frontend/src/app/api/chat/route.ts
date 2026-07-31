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
// A multi-meme batch generates sequentially (see routers/chat.py's
// _stream_batch) and can plausibly take 15-40s end-to-end for several
// memes, worse right after Render's ~30s free-tier cold start — raise
// above whatever the platform default is.
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  const body = await req.json();
  // Growth Phase C — this hand-written route builds its own fetch to the
  // backend, so next.config.js's generic rewrite (which forwards headers
  // transparently) never applies here; the anon-identity header has to be
  // read off the incoming request and re-attached explicitly or it's
  // silently dropped before ever reaching FastAPI.
  const anonUser = req.headers.get("x-memegpt-user");

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/chat/`, {
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

  // Pipe the SSE stream straight through — no buffering
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
