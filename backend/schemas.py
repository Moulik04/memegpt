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
    message: str
    conversation_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    meme_count: Optional[int] = None  # explicit override — forces exactly N memes, clamped to
                                       # settings.max_memes_per_request; None = auto-detect


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


class FeedbackResponse(BaseModel):
    status: str
    rating: Literal["up", "down"]
