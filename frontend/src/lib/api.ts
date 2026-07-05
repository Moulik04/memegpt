import type {
  ExplainResponse,
  FeedbackRequest,
  ImageChatOptions,
  MemeGenerationRequest,
  MemeGenerationResponse,
  SSEEvent,
} from "@/types";

const BASE = "/api";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
 * Shared by sendChatStream and sendChatImageStream.
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

/**
 * Open an SSE stream to /chat/ and call `onEvent` for each parsed event.
 * Returns when the stream ends or an error occurs.
 */
export async function sendChatStream(
  message: string,
  conversationId: string | undefined,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const res = await fetch(`${BASE}/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }

  await _consumeSSE(res, onEvent);
}

/**
 * Phase 1 (Mode 1: image as context) — uploads a photo (+ optional text) to
 * /chat/image/ and streams the same SSE event shape as sendChatStream.
 */
export async function sendChatImageStream(
  file: File,
  options: ImageChatOptions,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const form = new FormData();
  form.append("image", file);
  if (options.message) form.append("message", options.message);
  if (options.conversationId) form.append("conversation_id", options.conversationId);

  const res = await fetch(`${BASE}/chat/image/`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${err}`);
  }

  await _consumeSSE(res, onEvent);
}

export async function postFeedback(req: FeedbackRequest): Promise<void> {
  await post("/feedback/", req);
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
