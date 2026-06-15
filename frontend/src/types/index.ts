export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  meme_url?: string;
  timestamp: string;
  template_id?: string; // populated on assistant turns for feedback attribution
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

export interface FeedbackRequest {
  template_id: string;
  rating: "up" | "down";
  texts?: Record<string, string>;
  conversation_id?: string;
  user_message?: string;
}

export interface ThinkingEvent {
  type: "thinking";
  stage: string;
  message: string;
  template_id?: string;
}

export interface DoneEvent {
  type: "done";
  conversation_id: string;
  message: ChatMessage;
  template_used?: string;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type SSEEvent = ThinkingEvent | DoneEvent | ErrorEvent;
