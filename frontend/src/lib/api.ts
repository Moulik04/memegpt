import type {
  ExplainResponse,
  FeedbackRequest,
  ImageChatOptions,
  MemeGenerationRequest,
  MemeGenerationResponse,
  SSEEvent,
} from "@/types";
import { getOrCreateAnonId } from "@/lib/identity";

const BASE = "/api";
// Image uploads go straight to the backend, not through /api's Vercel proxy
// route — Vercel serverless functions cap request bodies at 4.5MB, which
// multiple photos blow past easily. The backend's CORS is already wide open
// (CORS_ALLOW_ALL_ORIGINS) for exactly this, and NEXT_PUBLIC_API_BASE is
// already browser-reachable in every deployment topology (see memeImageUrl).
const BACKEND_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const ANON_HEADER = "X-MemeGPT-User";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", [ANON_HEADER]: getOrCreateAnonId() },
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
    headers: { "Content-Type": "application/json", [ANON_HEADER]: getOrCreateAnonId() },
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
      headers: { [ANON_HEADER]: getOrCreateAnonId() },
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
// hand-written /api/me/ route exists (or is needed): next.config.js's
// generic /api/:path* rewrite forwards headers/method transparently, unlike
// the hand-rolled /api/chat/ and /api/feedback/ routes above.
export async function forgetMe(): Promise<void> {
  await fetch(`${BASE}/me/`, {
    method: "DELETE",
    headers: { [ANON_HEADER]: getOrCreateAnonId() },
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
