export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  meme_url?: string;
  timestamp: string;
}

export interface ChatResponse {
  conversation_id: string;
  message: ChatMessage;
  template_used?: string;
}

export interface MemeGenerationRequest {
  template_id: string;
  texts: Record<string, string>;
}

export interface MemeGenerationResponse {
  meme_url: string;
  template_id: string;
  texts: Record<string, string>;
}

export interface ExplainResponse {
  template_id: string;
  name: string;
  description: string;
  tags: string[];
  usage_count: number;
  recent_uses: Array<Record<string, string>>;
}
