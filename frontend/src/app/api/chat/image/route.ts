/**
 * App Router API route for /api/chat/image/ — Phase 1 multimodal endpoint.
 *
 * Unlike ../route.ts (which re-parses and re-stringifies a JSON body), this
 * route must pass the incoming multipart body through RAW: forward the
 * request's ReadableStream and its original Content-Type header (which
 * carries the multipart boundary) straight to the backend. `duplex: "half"`
 * is required by Node's fetch whenever a ReadableStream is used as a body.
 *
 * The response side (SSE passthrough) is identical to ../route.ts.
 */

import { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const contentType = req.headers.get("content-type") ?? "";

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/chat/image/`, {
      method: "POST",
      headers: { "Content-Type": contentType },
      body: req.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });
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
