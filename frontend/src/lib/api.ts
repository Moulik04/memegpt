import type {
  ArcCardResponse,
  ArcStats,
  ConversationSummary,
  ExplainResponse,
  FeedbackRequest,
  ImageChatOptions,
  MemeGenerationRequest,
  MemeGenerationResponse,
  NoticeReason,
  PersistedMessage,
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

// FastAPI's HTTPException bodies are `{"detail": "<user-facing message>"}`
// (e.g. Make's moderation refusal) — surface that string directly instead
// of the raw `"400 Bad Request: {\"detail\":...}"` blob callers used to
// throw, since several call sites (MakeView's genError) render the
// message as-is.
// An error response, with the backend's `reason` when it gave one (see
// NoticeReason) so a caller can tell "the daily budget is used up" from a
// failure and show the budget meme with it.
export class ApiError extends Error {
  reason?: NoticeReason;

  constructor(message: string, reason?: NoticeReason) {
    super(message);
    this.name = "ApiError";
    this.reason = reason;
  }
}

async function _apiError(res: Response): Promise<ApiError> {
  const raw = await res.text();
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed?.detail === "string") return new ApiError(parsed.detail, parsed.reason);
  } catch {
    // Not JSON — fall through to the raw body below.
  }
  return new ApiError(`${res.status} ${res.statusText}: ${raw}`);
}

const VISIT_HEADER = "X-MemeGPT-Visit";

// For requests the browser sends straight to the backend. The frontend's
// server signs a short-lived note of the address it saw (app/api/visit), so
// the backend can count its limits per visitor there too. Best effort: with
// no token the upload still goes, counted against its connection.
async function visitHeader(): Promise<Record<string, string>> {
  try {
    const res = await fetch(`${BASE}/visit`, { cache: "no-store" });
    if (!res.ok) return {};
    const { token } = (await res.json()) as { token?: string | null };
    return token ? { [VISIT_HEADER]: token } : {};
  } catch {
    return {};
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await _apiError(res);
  }
  return res.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) {
    throw await _apiError(res);
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
  rememberLore?: boolean,
  conversationRowId?: string
): Promise<void> {
  const body: Record<string, unknown> = {
    message,
    conversation_id: conversationId,
    conversation_row_id: conversationRowId,
  };
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
    throw await _apiError(res);
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
  if (options.conversationRowId) form.append("conversation_row_id", options.conversationRowId);
  if (surface === "lore") {
    if (options.memeCount) form.append("meme_count", String(options.memeCount));
    if (options.rememberLore) form.append("remember_lore", "true");
  }

  let res: Response;
  try {
    res = await fetch(`${BACKEND_BASE}/${surface}/image/`, {
      method: "POST",
      headers: { ...(await authHeaders()), ...(await visitHeader()) },
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
    throw await _apiError(res);
  }

  await _consumeSSE(res, onEvent);
}

export async function postFeedback(req: FeedbackRequest): Promise<void> {
  await post("/feedback/", req);
}

// Erases every row tied to this browser's anon id. No hand-written
// /api/me route exists (or is needed): next.config.js's generic
// /api/:path* rewrite forwards headers/method transparently, unlike the
// hand-rolled /api/chat/ and /api/feedback/ routes above. No trailing
// slash — Next normalizes one away before the rewrite even runs, and
// backend/routers/me.py is registered at "" for the same reason — so
// requesting it directly skips two avoidable redirect hops.
export async function forgetMe(): Promise<void> {
  await deleteOrThrow(`${BASE}/me`, "MemeGPT couldn't finish erasing your data. Please try again.");
}

// For the two requests that erase a user's data. fetch() resolves normally
// on a 4xx/5xx, so an erase the server refused or could not finish would
// otherwise look exactly like one that worked. Throws with the server's own
// explanation when it sent one.
async function deleteOrThrow(url: string, fallbackMessage: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { method: "DELETE", headers: await authHeaders() });
  } catch {
    throw new Error("MemeGPT couldn't reach the server, so the erase may not have happened. Check your connection and try again.");
  }
  if (res.ok) return;
  let detail: unknown;
  try {
    detail = (await res.json())?.detail;
  } catch {
    // Not JSON (a proxy error page, say) — the fallback below covers it.
  }
  throw new Error(typeof detail === "string" && detail ? detail : fallbackMessage);
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

export async function listTemplates(): Promise<ExplainResponse[]> {
  return get<ExplainResponse[]>("/explain/");
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
    headers: await authHeaders(),
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
    headers: await authHeaders(),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }
  return res.json() as Promise<ArcCardResponse>;
}

// Growth Phase H, Stage 3 — persisted chat history (signed-in only). All
// four ride next.config.js's generic /api/:path* rewrite (headers forward
// transparently) — no hand-written proxy route needed, same precedent as
// /me and /arc, since none of these are SSE.
export async function listConversations(surface: Surface): Promise<ConversationSummary[]> {
  const res = await fetch(`${BASE}/conversations?surface=${surface}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) return [];
  return res.json() as Promise<ConversationSummary[]>;
}

export async function createConversation(surface: Surface): Promise<{ id: string; surface: string }> {
  const res = await fetch(`${BASE}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ surface }),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }
  return res.json() as Promise<{ id: string; surface: string }>;
}

export async function getConversationMessages(id: string): Promise<PersistedMessage[]> {
  const res = await fetch(`${BASE}/conversations/${id}/messages`, {
    headers: await authHeaders(),
  });
  if (!res.ok) return [];
  return res.json() as Promise<PersistedMessage[]>;
}

export async function renameConversation(id: string, title: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  await deleteOrThrow(`${BASE}/conversations/${id}`, "MemeGPT couldn't delete that chat. Please try again.");
}
