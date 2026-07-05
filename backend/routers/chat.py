"""
POST /chat/       — main conversational endpoint (text), returns Server-Sent Events.
POST /chat/image/ — Phase 1 multimodal endpoint (image as context), same SSE contract.

SSE event stream:
  {"type": "thinking", "stage": "analyzing",  "message": "..."}
  {"type": "thinking", "stage": "rendering",  "template_id": "...", "message": "..."}
  {"type": "done",     "conversation_id": "...", "message": {...}, "template_used": "..."}
  {"type": "error",    "message": "..."}
"""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from config import get_settings
from image_processing.compositor import compose_meme
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import parse_intent
from nlp.vision import VisionUnavailable, describe_image
from rate_limit import limiter
from schemas import ChatMessage, ChatRequest, ChatResponse
from uploads.safe_ingest import ModerationRejected, UploadRejected, safe_ingest
from vector_db.chroma_client import log_usage

router = APIRouter()

_GENERIC_UPLOAD_REFUSAL = "That image couldn't be processed — try a different one."
_DESCRIBE_IN_WORDS_PROMPT = (
    "I couldn't quite look at that image right now — mind describing the "
    "situation in words instead?"
)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_chat_turn(user_message: str, conversation_id: str) -> AsyncGenerator[str, None]:
    """The shared analyzing -> parse_intent -> rendering -> compose_meme ->
    log_usage -> done sequence, used identically by both /chat/ and
    /chat/image/ once each has produced a plain-text user_message."""
    yield _sse({
        "type": "thinking",
        "stage": "analyzing",
        "message": "Reading your vibe...",
    })

    # Retrieve recent templates from this conversation to avoid repeats
    recent = get_recent_templates(conversation_id, n=5)

    try:
        intent = await parse_intent(user_message, avoid_templates=recent)
    except Exception as exc:
        yield _sse({"type": "error", "message": str(exc)})
        return

    friendly_name = intent.template_id.replace("_", " ")
    yield _sse({
        "type": "thinking",
        "stage": "rendering",
        "template_id": intent.template_id,
        "message": f"Crafting the perfect {friendly_name} meme...",
    })

    try:
        meme_url = await compose_meme(
            template_id=intent.template_id,
            texts=intent.texts,
        )
    except FileNotFoundError as exc:
        yield _sse({"type": "error", "message": f"Template not found: {exc}"})
        return

    add_turn(conversation_id, intent.template_id)

    log_usage(
        template_id=intent.template_id,
        top_text=next(iter(intent.texts.values()), ""),
        bottom_text=list(intent.texts.values())[-1] if len(intent.texts) > 1 else "",
        conversation_id=conversation_id,
    )

    reply = ChatMessage(role="assistant", content="", meme_url=meme_url)
    response = ChatResponse(
        conversation_id=conversation_id,
        message=reply,
        template_used=intent.template_id,
    )

    yield _sse({"type": "done", **response.model_dump(mode="json")})


def _sse_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/")
async def chat(request: ChatRequest):
    """
    Streams SSE events as the meme is being generated:
      1. 'analyzing' — LLM is parsing the user message
      2. 'rendering'  — compositor is drawing the meme
      3. 'done'       — full ChatResponse payload
    """
    conversation_id = request.conversation_id or ""
    return _sse_response(_stream_chat_turn(request.message, conversation_id))


@router.post("/image/")
@limiter.limit(get_settings().upload_rate_limit)
async def chat_with_image(
    request: Request,  # required by slowapi's key_func, unused otherwise
    image: UploadFile = File(...),
    message: str | None = Form(None),
    conversation_id: str | None = Form(None),
):
    """
    Phase 1 (Mode 1: image as context) — uploads a photo, describes it via
    the vision layer, merges the description with any user text, and feeds
    the result into the EXACT SAME _stream_chat_turn() used by /chat/.

    ALL uploaded images pass through uploads/safe_ingest.safe_ingest() —
    never bypass it. Every failure path below returns a generic, content-
    free refusal; category-only details are logged inside safe_ingest.py,
    never the image bytes or a description of what was detected.
    """
    conv_id = conversation_id or ""

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            clean = await safe_ingest(image)
        except (ModerationRejected, UploadRejected):
            yield _sse({"type": "error", "message": _GENERIC_UPLOAD_REFUSAL})
            return

        try:
            description = await describe_image(clean.image, user_text=message)
        except VisionUnavailable:
            # Graceful degrade — a normal assistant reply, not a hard error.
            reply = ChatMessage(role="assistant", content=_DESCRIBE_IN_WORDS_PROMPT)
            response = ChatResponse(conversation_id=conv_id, message=reply)
            yield _sse({"type": "done", **response.model_dump(mode="json")})
            return

        # Phase 2 (canvas mode) isn't built yet — degrade gracefully rather
        # than half-implementing it or dead-ending the user.
        merged = description.situation if not message else f"{description.situation} {message.strip()}"
        async for event in _stream_chat_turn(merged, conv_id):
            yield event

    return _sse_response(event_stream())
