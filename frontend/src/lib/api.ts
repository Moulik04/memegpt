import type {
  ArcCardResponse,
  ArcStats,
  ExplainResponse,
  FeedbackRequest,
  ImageChatOptions,
  MemeGenerationRequest,
  MemeGenerationResponse,
  SSEEvent,
} from "@/types";
import { getOrCreateAnonId } from "@/lib/identity";
import { supabase } from "@/lib/supabaseClient";

const BASE = "/api";
// Image uploads go straight to the backend, not through /api's Vercel proxy
// route — Vercel serverless functions cap request bodies at 4.5MB, which
// multiple photos blow past easily. The backend's CORS is already wide open
// (CORS_ALLOW_ALL_ORIGINS) for exactly this, and NEXT_PUBLIC_API_BASE is
// already browser-reachable in every deployment topology (see memeImageUrl).
const BACKEND_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const ANON_HEADER = "X-MemeGPT-User";

/**
 * Growth Phase H, Stage 2 — the single place every call site attaches
 * identity headers, replacing 6 previously-independent inline copies of
 * `{ [ANON_HEADER]: getOrCreateAnonId() }`. Always attaches the anon
 * header (unaffected by sign-in state — Phase C's identity never stops
 * being sent); additionally attaches `Authorization: Bearer <token>` when
 * a Supabase session exists, so the backend can verify a real user_id
 * alongside the anon one. A no-op when Supabase Auth isn't configured
 * (`supabase` is null) or there's no active session — no different from
 * today's anon-only behavior in either case.
 */
async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { [ANON_HEADER]: getOrCreateAnonId() };
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }
  return res.json() as Promise<T>;
}

/**
 * Read an SSE Response body, calling `onEvent` for each parsed event.
 * Shared by sendStream and sendImageStream.
 */
async function _consumeSSE(res: Response, onEvent: (event: SSEEvent) => void): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6)) as SSEEvent;
        onEvent(event);
      } catch {
        // incomplete chunk, will be retried next iteration
      }
    }
  }
}

export type Surface = "chat" | "lore";

/**
 * Open an SSE stream to the given surface's text endpoint (/api/chat/ or
 * /api/lore/, Growth Phase D split) and call `onEvent` for each parsed event.
 * meme_count / remember_lore only exist on the Lore endpoint's request model,
 * so they're only sent for surface="lore".
 */
export async function sendStream(
  surface: Surface,
  message: string,
  conversationId: string | undefined,
  onEvent: (event: SSEEvent) => void,
  memeCount?: number,
  rememberLore?: boolean
): Promise<void> {
  const body: Record<string, unknown> = { message, conversation_id: conversationId };
  if (surface === "lore") {
    body.meme_count = memeCount;
    body.remember_lore = rememberLore ?? false;
  }

  const res = await fetch(`${BASE}/${surface}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }

  await _consumeSSE(res, onEvent);
}

/**
 * Uploads one or more photos (+ optional text) to the given surface's image
 * endpoint (/chat/image/ or /lore/image/) and streams the same SSE event
 * shape as sendStream. Posts DIRECTLY to the backend (not the /api proxy) to
 * dodge Vercel's 4.5MB function body cap — see the BACKEND_BASE note above.
 * meme_count / remember_lore are Lore-only.
 */
export async function sendImageStream(
  surface: Surface,
  files: File[],
  options: ImageChatOptions,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const form = new FormData();
  for (const file of files) form.append("images", file);
  if (options.message) form.append("message", options.message);
  if (options.conversationId) form.append("conversation_id", options.conversationId);
  if (surface === "lore") {
    if (options.memeCount) form.append("meme_count", String(options.memeCount));
    if (options.rememberLore) form.append("remember_lore", "true");
  }

  let res: Response;
  try {
    res = await fetch(`${BACKEND_BASE}/${surface}/image/`, {
      method: "POST",
      headers: await authHeaders(),
      body: form,
    });
  } catch {
    throw new Error(
      "Couldn't reach the server to upload those photos — check your connection and try again."
    );
  }

  if (!res.ok) {
    if (res.status === 413) {
      throw new Error("Those photos are too large to upload together — try fewer or smaller images.");
    }
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }

  await _consumeSSE(res, onEvent);
}

export async function postFeedback(req: FeedbackRequest): Promise<void> {
  await post("/feedback/", req);
}

// Growth Phase C — erases every row tied to this browser's anon id. No
// hand-written /api/me route exists (or is needed): next.config.js's
// generic /api/:path* rewrite forwards headers/method transparently, unlike
// the hand-rolled /api/chat/ and /api/feedback/ routes above. No trailing
// slash — Next normalizes one away before the rewrite even runs (found
// while verifying Arc's endpoint end-to-end; matches backend/routers/me.py
// being registered at "" for the same reason), so requesting it directly
// skips two avoidable redirect hops.
export async function forgetMe(): Promise<void> {
  await fetch(`${BASE}/me`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
}

// Growth Phase H, Stage 2 — links this browser's anonymous history to the
// account that just signed in. Called once by AuthProvider.tsx on
// Supabase's SIGNED_IN event; safe to call again (backend-side idempotent).
// No trailing slash, same "" registration precedent as forgetMe()/getArc().
export async function linkAnonAccount(): Promise<void> {
  await fetch(`${BASE}/auth/link-anon`, {
    method: "POST",
    headers: await authHeaders(),
  });
}

export async function generateMeme(
  req: MemeGenerationRequest
): Promise<MemeGenerationResponse> {
  return post<MemeGenerationResponse>("/generate/", req);
}

export async function explainMeme(
  template_id: string,
  conversation_id?: string
): Promise<ExplainResponse> {
  return post<ExplainResponse>("/explain/", { template_id, conversation_id });
}

export function memeImageUrl(relativeUrl: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
  return `${base}${relativeUrl}`;
}

// Growth Phase D — Arc. Both ride next.config.js's generic /api/:path*
// rewrite (which forwards headers transparently) rather than a hand-written
// proxy route — same precedent as /me, no SSE involved here to force one.
// getArc has no trailing slash before the query string, same reasoning as
// forgetMe() above — matches backend/routers/arc.py's GET route being
// registered at "".
export async function getArc(tz: string): Promise<ArcStats> {
  const res = await fetch(`${BASE}/arc?tz=${encodeURIComponent(tz)}`, {
    headers: { [ANON_HEADER]: getOrCreateAnonId() },
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }
  return res.json() as Promise<ArcStats>;
}

export async function createArcCard(tz: string): Promise<ArcCardResponse> {
  const res = await fetch(`${BASE}/arc/card?tz=${encodeURIComponent(tz)}`, {
    method: "POST",
    headers: { [ANON_HEADER]: getOrCreateAnonId() },
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }
  return res.json() as Promise<ArcCardResponse>;
}
