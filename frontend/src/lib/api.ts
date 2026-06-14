import type {
  ChatMessage,
  ChatResponse,
  ExplainResponse,
  MemeGenerationRequest,
  MemeGenerationResponse,
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

export async function sendChat(
  message: string,
  conversationId?: string
): Promise<ChatResponse> {
  return post<ChatResponse>("/chat/", { message, conversation_id: conversationId });
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
