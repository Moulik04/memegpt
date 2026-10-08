import type { NextRequest } from "next/server";

// Server-only helpers for the hand-written /api proxy routes.
//
// The backend sees every proxied request as coming from this server, so it
// cannot tell visitors apart for its limits unless this server says who is
// asking. It says so with the visitor's address plus PROXY_SHARED_SECRET,
// which the backend also holds: without the secret the backend ignores the
// address, so nobody calling the backend directly can make one up.
//
// The address is only as good as the host's headers. Vercel sets these
// itself and discards whatever the browser sent. Anywhere a browser could
// set them, leave PROXY_SHARED_SECRET unset.

const ADDRESS_HEADERS = ["x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"];

export function clientAddress(req: NextRequest): string | null {
  for (const name of ADDRESS_HEADERS) {
    const first = req.headers.get(name)?.split(",")[0]?.trim();
    if (first) return first;
  }
  return null;
}

/** Identity headers to pass on, plus the visitor's address when it can be vouched for. */
export function backendHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};
  const anonUser = req.headers.get("x-memegpt-user");
  const authorization = req.headers.get("authorization");
  if (anonUser) headers["X-MemeGPT-User"] = anonUser;
  if (authorization) headers["Authorization"] = authorization;

  const secret = process.env.PROXY_SHARED_SECRET;
  const address = clientAddress(req);
  if (secret && address) {
    headers["X-MemeGPT-Proxy-Secret"] = secret;
    headers["X-MemeGPT-Client-Address"] = address;
  }
  return headers;
}
