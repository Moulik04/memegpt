import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Hand-written, not the generic next.config.js rewrite — see
// api/generate/route.ts for why. Two handlers: GET lists every template
// (the Make picker grid), POST explains one (also used once a template
// is picked, for its caption-field structure). Neither needs
// identity/auth headers — template metadata is public.

export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/explain/`);
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return NextResponse.json({ detail: `Backend unreachable: ${err}` }, { status: 502 });
  }
  const data = await upstream.json();
  return NextResponse.json(data, { status: upstream.status });
}
