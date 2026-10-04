import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Coming-soon / maintenance mode — set MAINTENANCE_MODE=true (Vercel env
// var, requires a redeploy to take effect) to rewrite every route to the
// coming-soon page while a revamp is in progress. NextResponse.rewrite()
// (not redirect) keeps the real URL in the browser's address bar — a
// visitor at /chat still sees /chat, just served different content.
// Reversing this is just unsetting the env var and redeploying; nothing
// structural to undo.
const BYPASS_PREFIXES = ["/maintenance", "/_next"];
const BYPASS_EXACT = ["/favicon.ico", "/manifest.json", "/robots.txt"];
const STATIC_ASSET_PATTERN = /\.(png|jpg|jpeg|svg|ico|webp|json|txt|woff2?)$/;

// Preview pass — temporary, delete it together with maintenance mode.
// Opening any page with ?gate=<MAINTENANCE_BYPASS_SECRET> sets a cookie
// that lets that one browser through, then redirects to the same URL
// without the parameter so the secret doesn't stay in the address bar.
// The secret is a Vercel env var only. Unset, or shorter than
// PASS_MIN_SECRET_LENGTH, means no pass exists at all. The cookie holds a
// hash of the secret rather than the secret, so changing the secret
// revokes every pass already handed out.
const PASS_PARAM = "gate";
const PASS_COOKIE = "memegpt_gate";
const PASS_MIN_SECRET_LENGTH = 24;
const PASS_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

async function passToken(secret: string): Promise<string> {
  const bytes = new TextEncoder().encode(`${PASS_COOKIE}:${secret}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Checks every character whatever the first mismatch is, so response
// timing says nothing about how much of a guess was right.
function sameToken(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export async function middleware(request: NextRequest) {
  if (process.env.MAINTENANCE_MODE !== "true") {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  const isBypassed =
    BYPASS_EXACT.includes(pathname) ||
    BYPASS_PREFIXES.some((prefix) => pathname.startsWith(prefix)) ||
    STATIC_ASSET_PATTERN.test(pathname);

  if (isBypassed) {
    return NextResponse.next();
  }

  const secret = process.env.MAINTENANCE_BYPASS_SECRET ?? "";
  if (secret.length >= PASS_MIN_SECRET_LENGTH) {
    const expected = await passToken(secret);

    const offered = request.nextUrl.searchParams.get(PASS_PARAM);
    if (offered !== null) {
      // Right or wrong, strip the parameter and redirect. A wrong guess
      // just lands back on the coming-soon page.
      const clean = request.nextUrl.clone();
      clean.searchParams.delete(PASS_PARAM);
      const response = NextResponse.redirect(clean);
      response.headers.set("Cache-Control", "no-store");
      if (sameToken(await passToken(offered), expected)) {
        response.cookies.set(PASS_COOKIE, expected, {
          httpOnly: true,
          secure: request.nextUrl.protocol === "https:",
          sameSite: "lax",
          path: "/",
          maxAge: PASS_MAX_AGE_SECONDS,
        });
      }
      return response;
    }

    const held = request.cookies.get(PASS_COOKIE)?.value;
    if (held && sameToken(held, expected)) {
      return NextResponse.next();
    }
  }

  const url = request.nextUrl.clone();
  url.pathname = "/maintenance";
  return NextResponse.rewrite(url);
}

export const config = {
  // Keep the matcher itself minimal (just Next's own internals) — the
  // real bypass logic lives above, in plain readable conditionals, rather
  // than packed into one dense matcher regex.
  matcher: ["/((?!_next/static|_next/image).*)"],
};
