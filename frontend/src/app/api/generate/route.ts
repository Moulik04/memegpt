import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Hand-written, not the generic next.config.js rewrite — same reason as
// api/feedback/route.ts: the generic /api/:path* rewrite 308s on POST
// requests to a trailing-slash path (Next's own trailing-slash
// normalization firing before the rewrite runs), which broke every
// endpoint that's actually been exercised for real in this app.
//
// Identity headers ARE forwarded (this used to say they weren't needed —
// that was wrong: lib/api.ts's post() already attaches them to every call
// including this one, but this route silently dropped them before they
// ever reached the backend, which meant the backend had no way to
// attribute a Make-generated meme to anyone even after it started trying
// to. Same fix as chat/lore/feedback's routes.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const anonUser = req.headers.get("x-memegpt-user");
  const authorization = req.headers.get("authorization");
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/generate/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(anonUser ? { "X-MemeGPT-User": anonUser } : {}),
        ...(authorization ? { Authorization: authorization } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return NextResponse.json({ detail: `Backend unreachable: ${err}` }, { status: 502 });
  }
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
