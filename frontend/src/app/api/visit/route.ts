import { createHmac } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { clientAddress } from "@/lib/proxyHeaders";

// Photo uploads go from the browser straight to the backend (they are too
// large for this server's request limit), so this server cannot vouch for
// the visitor's address on the request itself. Instead it signs a
// short-lived token saying which address it saw, and the browser sends that
// along with the upload. The backend checks the signature with the same
// PROXY_SHARED_SECRET (backend/visitor.py, which holds the reference
// implementation of this format).
//
// Without a secret, or off a host that sets the address headers itself,
// there is nothing to sign: the upload goes without a token and the backend
// counts it against the connection it arrived on.

export const dynamic = "force-dynamic";

const TTL_SECONDS = 600;

export async function GET(req: NextRequest) {
  const secret = process.env.PROXY_SHARED_SECRET;
  const address = clientAddress(req);
  if (!secret || !address) {
    return NextResponse.json({ token: null }, { headers: { "Cache-Control": "no-store" } });
  }
  const expires = Math.floor(Date.now() / 1000) + TTL_SECONDS;
  const payload = `v1.${expires}.${Buffer.from(address).toString("base64url")}`;
  const signature = createHmac("sha256", secret).update(payload).digest("hex");
  return NextResponse.json(
    { token: `${payload}.${signature}` },
    { headers: { "Cache-Control": "no-store" } },
  );
}
