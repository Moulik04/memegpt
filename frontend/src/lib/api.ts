import type {
  ExplainResponse,
  FeedbackRequest,
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
  return `http://localhost:8000${relativeUrl}`;
}
