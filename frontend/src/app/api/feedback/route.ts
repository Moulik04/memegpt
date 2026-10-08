import { NextRequest, NextResponse } from "next/server";
import { backendHeaders } from "@/lib/proxyHeaders";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  // Growth Phase C — same header-forwarding fix as app/api/chat/route.ts:
  // this hand-written route bypasses next.config.js's generic rewrite, so
  // the anon-identity header must be read and re-attached explicitly.
  // Growth Phase H, Stage 2 — same fix for the Authorization bearer header.
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/feedback/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...backendHeaders(req) },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return NextResponse.json({ detail: `Backend unreachable: ${err}` }, { status: 502 });
  }
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
