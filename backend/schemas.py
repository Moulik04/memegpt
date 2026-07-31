from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core meme-template primitives
# ---------------------------------------------------------------------------

class TextBox(BaseModel):
    """A positioned bounding box inside a meme template where text is drawn."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str  # e.g. "top_text", "bottom_text", "left_panel"

    # Position & size in pixels (relative to the template image)
    x: int
    y: int
    width: int
    height: int

    # Rendering hints
    font_size: int = 40
    font_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 2
    align: Literal["left", "center", "right"] = "center"
    vertical_align: Literal["top", "center", "bottom"] = "center"
    uppercase: bool = True


class MemeTemplate(BaseModel):
    """Canonical record for a single meme template stored in ChromaDB + disk."""

    template_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    image_path: str  # relative to backend/templates/
    text_boxes: list[TextBox]
    tags: list[str] = []
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Lightweight usage history — each entry is {ts, top_text, bottom_text, conversation_id}
    history: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Chat / conversation layer
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    meme_url: Optional[str] = None  # populated on assistant turns
    meme_id: Optional[str] = None  # Growth Phase B — links feedback to a durable memes row
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    """Chat surface (Growth Phase D split) — the minimal-chrome conversational
    surface. No meme-count override, no Lore lexicon: Chat always auto-detects.
    Lore's extra controls live on LoreRequest, not here."""
    message: str
    conversation_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))


class LoreRequest(BaseModel):
    """Lore surface (Growth Phase D split) — big-context-dump surface with the
    explicit controls Chat deliberately doesn't expose. Same underlying
    segmentation/batch/SSE core as Chat; the difference is these two fields
    plus the surface stamp ("lore") the endpoint applies."""
    message: str
    conversation_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    meme_count: Optional[int] = None  # explicit override — forces exactly N memes, clamped to
                                       # settings.max_memes_per_request; None = auto-detect
    remember_lore: bool = False  # Growth Phase C — strictly opt-in Lore lexicon; see nlp/lexicon.py


class ChatResponse(BaseModel):
    conversation_id: str
    message: ChatMessage
    template_used: Optional[str] = None  # template_id for attribution


# ---------------------------------------------------------------------------
# NLP / intent layer
# ---------------------------------------------------------------------------

class IntentResponse(BaseModel):
    """Structured output produced by the LLM intent-routing step."""

    template_id: str
    texts: dict[str, str]   # text_box_label → caption, e.g. {"rejected_option": "..."}
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Vision layer (multimodal input — Phase 1: image as context)
# ---------------------------------------------------------------------------

class VisionDescription(BaseModel):
    """Output of nlp/vision.py's describe_image() — a plain-language
    description of an uploaded photo, phrased as if the user had typed it,
    fed straight into the existing parse_intent() as the user_message."""

    situation: str
    tone: Optional[str] = None           # reserved for future structured use
    visible_text: Optional[str] = None   # reserved for future structured use


# ---------------------------------------------------------------------------
# Segmentation layer (multi-context, multi-meme generation)
# ---------------------------------------------------------------------------

class SegmentedContext(BaseModel):
    """One distinct meme-worthy moment identified by nlp/segmentation.py's
    segment_contexts() out of a longer text dump and/or multiple photo
    descriptions. Each situation string is fed independently into the
    EXISTING parse_intent(), exactly like a single Phase 1 image description."""

    situation: str


# ---------------------------------------------------------------------------
# Growth Phase C — anonymous identity + memory v1
# ---------------------------------------------------------------------------

class LexiconExtractionResponse(BaseModel):
    """Output of nlp/lexicon.py's extract_lexicon() — short recurring
    names/nicknames/running-joke phrases pulled from a Lore dump, never the
    dump text itself. Empty when nothing recurring stood out."""

    terms: list[str]


class ForgetMeResponse(BaseModel):
    """DELETE /me/'s response — same shape/precedent as FeedbackResponse.
    Always "ok", whether there was data to erase or not (a no-op absence is
    not an error, matching every other db.py function's contract)."""

    status: str


# ---------------------------------------------------------------------------
# Generation layer
# ---------------------------------------------------------------------------

class MemeGenerationRequest(BaseModel):
    template_id: str
    texts: dict[str, str]  # label → text, e.g. {"top_text": "...", "bottom_text": "..."}


class MemeGenerationResponse(BaseModel):
    meme_url: str
    template_id: str
    texts: dict[str, str]


# ---------------------------------------------------------------------------
# Explain layer
# ---------------------------------------------------------------------------

class ExplainRequest(BaseModel):
    template_id: str
    conversation_id: Optional[str] = None


class ExplainResponse(BaseModel):
    template_id: str
    name: str
    description: str
    tags: list[str]
    usage_count: int
    recent_uses: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Feedback layer
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    template_id: str
    rating: Literal["up", "down"]
    texts: dict[str, str] = {}
    conversation_id: Optional[str] = None
    user_message: Optional[str] = None  # used to create positive few-shot example on 👍
    meme_id: Optional[str] = None  # Growth Phase B — links this rating to a durable memes row


class FeedbackResponse(BaseModel):
    status: str
    rating: Literal["up", "down"]


# ---------------------------------------------------------------------------
# Share pages (Growth Phase B)
# ---------------------------------------------------------------------------

class SharedMemeResponse(BaseModel):
    """GET /memes/{id}'s response — url + template display name ONLY.
    Never situation text, dump text, or captions (same privacy rule as
    the memes table itself). No listing endpoint exists anywhere, ever —
    this is reachable only via a specific, unguessable id."""

    url: str
    template_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Growth Phase D — Arc (personal meme stats)
# ---------------------------------------------------------------------------

class ArcTemplate(BaseModel):
    """One entry in ArcStats.top_templates — a template id, how many times
    it was this user's pick, and its roast (the parenthetical shown next to
    it, e.g. "(concerning)"), voiced by arc/copy.py."""

    template_id: str
    display_name: str
    count: int
    roast: str


class ArcStats(BaseModel):
    """GET /arc/'s response. has_enough=False means every other field is at
    its default (0 / None / []) — the frontend shows the empty state rather
    than treating this as an error. Private by construction: only reachable
    with the caller's own X-MemeGPT-User header, no listing endpoint."""

    has_enough: bool = False
    total_memes: int = 0
    date_span_start: Optional[str] = None  # ISO date, e.g. "2026-06-04"
    date_span_end: Optional[str] = None
    period_label: Optional[str] = None  # e.g. "Summer Arc" or "Your Arc"
    aura: int = 0
    tier: Optional[str] = None  # e.g. "main character (unwell)"
    top_templates: list[ArcTemplate] = []
    busiest_date: Optional[str] = None  # ISO date
    busiest_time_label: Optional[str] = None  # e.g. "2:14 AM", in the caller's tz
    hour_roast: Optional[str] = None
    chat_count: int = 0
    lore_count: int = 0
    split_roast: Optional[str] = None
    longest_streak_days: int = 0
    verdict: Optional[str] = None  # the closing line, e.g. "Character development: none detected. Arc continues."


class ArcCardResponse(BaseModel):
    """POST /arc/card's response — same shape/precedent as
    MemeGenerationResponse and FeedbackResponse. url is the rendered share
    card's public URL; meme_id is what /m/{meme_id} resolves to."""

    meme_id: str
    url: str
