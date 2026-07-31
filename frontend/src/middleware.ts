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

export function middleware(request: NextRequest) {
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
