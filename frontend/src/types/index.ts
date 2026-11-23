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
  // Set when this meme is another take on an earlier moment of the same
  // batch (index into that batch) rather than a moment of its own.
  takeOf?: number;
}

export interface MemeGenerationRequest {
  template_id: string;
  texts: Record<string, string>;
}

export interface MemeGenerationResponse {
  meme_url: string;
  template_id: string;
  texts: Record<string, string>;
  // The saved meme's id, for its /m/{id} share page. Absent from an older
  // backend.
  meme_id?: string;
}

export interface TextBoxInfo {
  label: string;
  description: string;
  // Where the compositor draws this caption, as percentages of the
  // template image. Absent from an older backend.
  x_pct?: number;
  y_pct?: number;
  w_pct?: number;
  h_pct?: number;
}

export interface ExplainResponse {
  template_id: string;
  name: string;
  description: string;
  tags: string[];
  usage_count: number;
  image_url: string | null;
  text_boxes: TextBoxInfo[];
}

export interface FeedbackRequest {
  template_id: string;
  rating: "up" | "down";
  conversation_id?: string;
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
  // Present only when an explicit meme count was larger than the number of
  // distinct moments: one entry per situation, the index of the moment it
  // is another take on, or null for a moment of its own.
  take_of?: (number | null)[];
  // Sent only to a request with include_source_lines (the redesign's Lore):
  // one entry per situation, the sorted numbers of the pasted lines it drew
  // on, or null to show the summary instead. See lib/sourceLines.ts.
  source_lines?: (number[] | null)[];
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
  take_of?: number;
}

export interface BatchDoneEvent {
  type: "batch_done";
  total: number;
  succeeded: number;
}

// Why MemeGPT could not make a meme, when it is one of the three expected
// cases (backend/notices.py). Absent on every other error.
//   busy          a per-minute limit; a minute is enough
//   site_budget   the shared daily AI budget; shown with a pre-made meme
//   visitor_limit this visitor's own daily allowance
export type NoticeReason = "busy" | "site_budget" | "visitor_limit";

// Set on an upload refusal, so the frontend words it (lib/notices.ts). An
// older backend sends none, and the message is shown as is.
export type UploadErrorCode =
  | "image_refused"
  | "file_too_large"
  | "unrecognized_file_type"
  | "dimensions_too_large"
  | "invalid_image"
  | "upload_failed";

// Set when another take on a Lore moment found no template it may use. The
// meme already shown stays.
export type TakeErrorCode = "no_fresh_template";

export interface ErrorEvent {
  type: "error";
  index?: number;
  total?: number;
  message: string;
  reason?: NoticeReason;
  code?: UploadErrorCode | TakeErrorCode;
}

export type SSEEvent = PlanEvent | ThinkingEvent | DoneEvent | BatchDoneEvent | ErrorEvent;

export interface ImageChatOptions {
  message?: string;
  conversationId?: string;
  memeCount?: number;
  rememberLore?: boolean;
  conversationRowId?: string;
}

// Lore-only options for a text request.
export interface LoreTextOptions {
  // Templates no meme in this request may use, for another take.
  excludeTemplates?: string[];
  // False only for another take, which needs no plan.
  includeSourceLines?: boolean;
}

// Growth Phase D — Arc. Mirrors backend/schemas.py's ArcTemplate/ArcStats.
export interface ArcTemplate {
  template_id: string;
  display_name: string;
  count: number;
  roast: string;
  image_url: string | null;
}

/** One rung of the tier ladder: a tier and the lowest aura that earns it. */
export interface ArcTier {
  name: string;
  min_aura: number;
}

export interface ArcStats {
  has_enough: boolean;
  total_memes: number;
  distinct_templates?: number;
  date_span_start: string | null;
  date_span_end: string | null;
  period_label: string | null;
  aura: number;
  tier: string | null;
  /** Every tier, top first, from the thresholds that grade the score.
   * Missing from a backend older than the ladder. */
  tiers?: ArcTier[];
  top_templates: ArcTemplate[];
  busiest_date: string | null;
  busiest_time_label: string | null;
  /** The same moment's hour, e.g. "2 AM". */
  busiest_hour_label?: string | null;
  hour_roast: string | null;
  chat_count: number;
  lore_count: number;
  make_count: number;
  split_roast: string | null;
  longest_streak_days: number;
  /** The punchlines after "memes generated this arc." and "consecutive days.". */
  volume_roast?: string | null;
  streak_roast?: string | null;
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
  thumbnail_url: string | null;
}

export interface PersistedMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meme_url: string | null;
  meme_id: string | null;
  created_at: string;
}
