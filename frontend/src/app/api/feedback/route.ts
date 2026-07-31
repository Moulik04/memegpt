import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  // Growth Phase C — same header-forwarding fix as app/api/chat/route.ts:
  // this hand-written route bypasses next.config.js's generic rewrite, so
  // the anon-identity header must be read and re-attached explicitly.
  const anonUser = req.headers.get("x-memegpt-user");
  const upstream = await fetch(`${BACKEND}/feedback/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(anonUser ? { "X-MemeGPT-User": anonUser } : {}),
    },
    body: JSON.stringify(body),
  });
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
