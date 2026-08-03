// One rendered meme within a chat turn. `situationText` is the specific
// segmented context that produced THIS meme — used to key per-meme
// feedback correctly when a batch produces several memes sharing one
// preceding user bubble (see ChatWindow.tsx's handleFeedback). `memeId`
// (Growth Phase B) links this meme to its durable Postgres row — used to
// attribute feedback and to build /m/{id} share links.
export interface MemeItem {
  url: string;
  templateId?: string;
  situationText: string;
  memeId?: string;
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
  meme_id?: string;
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
    meme_id?: string;
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
  rememberLore?: boolean;
  conversationRowId?: string;
}

// Growth Phase D — Arc. Mirrors backend/schemas.py's ArcTemplate/ArcStats.
export interface ArcTemplate {
  template_id: string;
  display_name: string;
  count: number;
  roast: string;
  image_url: string | null;
}

export interface ArcStats {
  has_enough: boolean;
  total_memes: number;
  date_span_start: string | null;
  date_span_end: string | null;
  period_label: string | null;
  aura: number;
  tier: string | null;
  top_templates: ArcTemplate[];
  busiest_date: string | null;
  busiest_time_label: string | null;
  hour_roast: string | null;
  chat_count: number;
  lore_count: number;
  split_roast: string | null;
  longest_streak_days: number;
  verdict: string | null;
}

export interface ArcCardResponse {
  meme_id: string;
  url: string;
}

// Growth Phase H, Stage 3 — persisted chat history (signed-in only).
// Mirrors backend/schemas.py's ConversationSummary/MessageOut.
export interface ConversationSummary {
  id: string;
  title: string | null;
  surface: "chat" | "lore";
  created_at: string;
  updated_at: string;
}

export interface PersistedMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meme_url: string | null;
  meme_id: string | null;
  created_at: string;
}
