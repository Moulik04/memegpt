import { NextRequest, NextResponse } from "next/server";
import { backendHeaders } from "@/lib/proxyHeaders";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Hand-written, not the generic next.config.js rewrite — see
// api/generate/route.ts for why. Two handlers: GET lists every template
// (the Make picker grid), POST explains one (also used once a template
// is picked, for its caption-field structure). Template metadata is public,
// so the headers passed on are not for access: they let the backend count
// its per-minute limit per visitor instead of once for everybody.

export async function GET(req: NextRequest) {
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/explain/`, { headers: backendHeaders(req) });
  } catch (err) {
    return NextResponse.json({ detail: `Backend unreachable: ${err}` }, { status: 502 });
  }
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/explain/`, {
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
