// One rendered meme within a chat turn. `situationText` is the specific
// segmented context that produced THIS meme — used to key per-meme
// feedback correctly when a batch produces several memes sharing one
// preceding user bubble (see ChatWindow.tsx's handleFeedback).
export interface MemeItem {
  url: string;
  templateId?: string;
  situationText: string;
}

// Client-side rendering type for the `messages` list. A user turn never
// has `memes`; an assistant turn accumulates ALL memes from one submission
// here — length 1 renders exactly like a single-meme reply always has,
// length 2+ renders as a swipeable carousel (see MessageBubble.tsx).
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  memes?: MemeItem[];
  // Preview URLs (blob:) for photos the user attached to this turn — kept
  // alive for the life of the conversation, not revoked after sending, so
  // the sent bubble can keep showing the actual photo (see ChatWindow.tsx).
  userImages?: string[];
  timestamp: string;
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

// Announces the resolved situations up front — only sent when there's more
// than one (see backend/routers/chat.py's _stream_batch). Lore renders this
// as a checklist that ticks off as "done" events land, keyed by index;
// Chat may ignore it or show a compact progress hint.
export interface PlanEvent {
  type: "plan";
  situations: string[];
  total: number;
}

export interface ThinkingEvent {
  type: "thinking";
  stage: string;
  index?: number;
  total?: number;
  message: string;
  template_id?: string;
}

// Mirrors ONE meme's wire data from a single backend "done" event — NOT the
// same shape as the client-side ChatMessage above, which accumulates many
// of these into one grouped bubble.
export interface DoneEvent {
  type: "done";
  index?: number;
  total?: number;
  conversation_id: string;
  message: {
    role: "assistant";
    content: string; // the situation text that produced this meme
    meme_url?: string;
    timestamp: string;
  };
  template_used?: string;
}

export interface BatchDoneEvent {
  type: "batch_done";
  total: number;
  succeeded: number;
}

export interface ErrorEvent {
  type: "error";
  index?: number;
  total?: number;
  message: string;
}

export type SSEEvent = PlanEvent | ThinkingEvent | DoneEvent | BatchDoneEvent | ErrorEvent;

export interface ImageChatOptions {
  message?: string;
  conversationId?: string;
  memeCount?: number;
}
