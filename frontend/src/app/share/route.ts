/**
 * PWA share-target intake — POST-only, never a page a user navigates to
 * directly (a stray GET, e.g. a stale bookmark, redirects to /lore).
 *
 * manifest.json's share_target.action points here with
 * method: "POST", enctype: "multipart/form-data". The OS share sheet POSTs
 * shared images/text/title straight to this route.
 *
 * This relays the multipart body server-to-server to the backend's
 * POST /share-intake/ (same proxy pattern as app/api/chat/route.ts), which
 * stashes it in memory and returns a short-lived token — the stash lives on
 * the backend (a single persistent Render instance) rather than here,
 * because this frontend is Vercel-hosted serverless and has no guarantee
 * that two requests moments apart hit the same instance/module scope.
 *
 * Per the Web Share Target spec, a POST share_target must respond with an
 * HTTP redirect (303) to avoid a duplicate POST if the destination page is
 * refreshed — redirects into /lore?intake=<token>, which fetches and
 * consumes the stash on mount but does NOT auto-submit it.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  return NextResponse.redirect(new URL("/lore", req.url));
}

export async function POST(req: NextRequest) {
  const contentType = req.headers.get("content-type") ?? "";

  try {
    const upstream = await fetch(`${BACKEND}/share-intake/`, {
      method: "POST",
      headers: { "Content-Type": contentType },
      body: req.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    if (!upstream.ok) {
      return NextResponse.redirect(new URL("/lore", req.url), 303);
    }

    const { token } = (await upstream.json()) as { token: string };
    return NextResponse.redirect(new URL(`/lore?intake=${token}`, req.url), 303);
  } catch {
    // Backend unreachable — still land the user in Lore rather than
    // erroring the whole share sheet; they can just re-attach manually.
    return NextResponse.redirect(new URL("/lore", req.url), 303);
  }
}
