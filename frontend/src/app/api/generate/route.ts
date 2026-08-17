import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Hand-written, not the generic next.config.js rewrite — same reason as
// api/feedback/route.ts: the generic /api/:path* rewrite 308s on POST
// requests to a trailing-slash path (Next's own trailing-slash
// normalization firing before the rewrite runs), which broke every
// endpoint that's actually been exercised for real in this app. No
// identity/auth headers needed here — /generate/ (Phase 4's manual
// meme-maker) is a stateless template+texts→image endpoint, unlike
// chat/lore/feedback.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const upstream = await fetch(`${BACKEND}/generate/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
