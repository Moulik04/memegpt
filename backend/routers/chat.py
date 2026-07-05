"""
POST /chat/       — main conversational endpoint (text), returns Server-Sent Events.
POST /chat/image/ — Phase 1 multimodal endpoint (image-as-context, 1+ photos), same SSE contract.

Both routes flow through the same batch pipeline (_stream_batch): a
submission resolves into 1..N distinct "situations" (nlp/segmentation.py's
resolve_contexts — a no-op fast path for the common case of one short
message or one photo), and each situation is rendered into its own meme via
_stream_chat_turn, sharing one HTTP response/SSE stream.

SSE event stream:
  {"type": "thinking", "stage": "analyzing",  "index": 0, "total": 1, "message": "..."}
  {"type": "thinking", "stage": "rendering",  "index": 0, "total": 1, "template_id": "...", "message": "..."}
  {"type": "done",     "index": 0, "total": 1, "conversation_id": "...", "message": {...}, "template_used": "..."}
  {"type": "batch_done", "total": 1, "succeeded": 1}
  {"type": "error",    "index": 0, "total": 1, "message": "..."}
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from config import get_settings
from image_processing.compositor import compose_meme
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import parse_intent
from nlp.segmentation import resolve_contexts
from nlp.vision import describe_image
from rate_limit import limiter
from schemas import ChatMessage, ChatRequest, ChatResponse, VisionDescription
from uploads.safe_ingest import CleanImage, ModerationRejected, UploadRejected, safe_ingest
from vector_db.chroma_client import log_usage

router = APIRouter()

_GENERIC_UPLOAD_REFUSAL = "That image couldn't be processed — try a different one."
_DESCRIBE_IN_WORDS_PROMPT = (
    "I couldn't quite look at that image right now — mind describing the "
    "situation in words instead?"
)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_chat_turn(
    user_message: str,
    conversation_id: str,
    index: int = 0,
    total: int = 1,
) -> AsyncGenerator[dict, None]:
    """The shared analyzing -> parse_intent -> rendering -> compose_meme ->
    log_usage -> done sequence for ONE situation. Yields raw event dicts —
    the caller (_stream_batch) serializes them to SSE strings, so index/total
    can be merged in centrally without every event constructor repeating it.
    `content` on the reply carries the situation text itself (previously
    always ""), which the frontend uses to key per-meme feedback correctly
    when several memes in one batch share a single preceding user bubble."""
    yield {
        "type": "thinking",
        "stage": "analyzing",
        "index": index,
        "total": total,
        "message": "Reading your vibe...",
    }

    # Retrieve recent templates from this conversation to avoid repeats
    recent = get_recent_templates(conversation_id, n=5)

    try:
        intent = await parse_intent(user_message, avoid_templates=recent)
    except Exception as exc:
        yield {"type": "error", "index": index, "total": total, "message": str(exc)}
        return

    friendly_name = intent.template_id.replace("_", " ")
    yield {
        "type": "thinking",
        "stage": "rendering",
        "index": index,
        "total": total,
        "template_id": intent.template_id,
        "message": f"Crafting the perfect {friendly_name} meme...",
    }

    try:
        meme_url = await compose_meme(
            template_id=intent.template_id,
            texts=intent.texts,
        )
    except FileNotFoundError as exc:
        yield {"type": "error", "index": index, "total": total, "message": f"Template not found: {exc}"}
        return

    add_turn(conversation_id, intent.template_id)

    log_usage(
        template_id=intent.template_id,
        top_text=next(iter(intent.texts.values()), ""),
        bottom_text=list(intent.texts.values())[-1] if len(intent.texts) > 1 else "",
        conversation_id=conversation_id,
    )

    reply = ChatMessage(role="assistant", content=user_message, meme_url=meme_url)
    response = ChatResponse(
        conversation_id=conversation_id,
        message=reply,
        template_used=intent.template_id,
    )

    yield {"type": "done", "index": index, "total": total, **response.model_dump(mode="json")}


async def _stream_batch(situations: list[str], conversation_id: str) -> AsyncGenerator[str, None]:
    """Runs each situation through _stream_chat_turn IN SEQUENCE (not
    parallel — this lets each context's avoid_templates see the previous
    context's just-picked template via conversation_store's recency
    tracking, so repeated/padded situations naturally get diverse templates
    for free), yielding every event as it happens so memes appear
    progressively rather than all at once at the end."""
    total = len(situations)
    succeeded = 0
    for i, situation in enumerate(situations):
        async for event in _stream_chat_turn(situation, conversation_id, index=i, total=total):
            if event.get("type") == "done":
                succeeded += 1
            yield _sse(event)
    yield _sse({"type": "batch_done", "total": total, "succeeded": succeeded})


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
    Streams SSE events as one or more memes are generated — resolve_contexts
    decides (with zero added latency for a normal short message) whether
    this is one situation or several.
    """
    conversation_id = request.conversation_id or ""
    contexts = await resolve_contexts(request.message, None, request.meme_count)
    return _sse_response(_stream_batch(contexts, conversation_id))


@router.post("/image/")
@limiter.limit(get_settings().upload_rate_limit)
async def chat_with_image(
    request: Request,  # required by slowapi's key_func, unused otherwise
    images: list[UploadFile] = File(...),
    message: str | None = Form(None),
    conversation_id: str | None = Form(None),
    meme_count: int | None = Form(None),
):
    """
    Phase 1 (Mode 1: image as context) — uploads 1+ photos, describes each
    via the vision layer, resolves the descriptions (+ any user text) into
    1..N situations, and feeds each into the EXACT SAME _stream_batch used
    by /chat/.

    ALL uploaded images pass through uploads/safe_ingest.safe_ingest() —
    never bypass it. A content-moderation failure on ANY image aborts the
    WHOLE request with today's generic refusal (a moderation hit is an
    adversarial signal, unlike a size/type failure, and skip-and-continue
    would leak a per-image "this one got silently dropped" signal that
    uploads/moderation.py's category-never-echoed invariant exists to
    prevent). A non-safety UploadRejected on one image in a batch just
    drops that image and continues with the rest.
    """
    conv_id = conversation_id or ""

    async def event_stream() -> AsyncGenerator[str, None]:
        settings = get_settings()
        capped_images = images[: settings.max_images_per_request]

        ingest_results = await asyncio.gather(
            *[safe_ingest(img) for img in capped_images],
            return_exceptions=True,
        )

        if any(isinstance(r, ModerationRejected) for r in ingest_results):
            yield _sse({"type": "error", "message": _GENERIC_UPLOAD_REFUSAL})
            return

        clean_images = [r for r in ingest_results if isinstance(r, CleanImage)]

        if not clean_images:
            # All images failed non-safety validation (too big/wrong type).
            # Degrade to a text-only turn if there's accompanying text,
            # rather than hard-refusing when the user's words are still usable.
            if message:
                contexts = await resolve_contexts(message, None, meme_count)
                async for event in _stream_batch(contexts, conv_id):
                    yield event
                return
            yield _sse({"type": "error", "message": _GENERIC_UPLOAD_REFUSAL})
            return

        description_results = await asyncio.gather(
            *[describe_image(ci.image, user_text=message) for ci in clean_images],
            return_exceptions=True,
        )
        descriptions = [d.situation for d in description_results if isinstance(d, VisionDescription)]

        if not descriptions:
            # Every vision call failed (VisionUnavailable) — graceful
            # degrade, a normal assistant reply, not a hard error.
            reply = ChatMessage(role="assistant", content=_DESCRIBE_IN_WORDS_PROMPT)
            response = ChatResponse(conversation_id=conv_id, message=reply)
            yield _sse({"type": "done", **response.model_dump(mode="json")})
            return

        contexts = await resolve_contexts(message, descriptions, meme_count)
        async for event in _stream_batch(contexts, conv_id):
            yield event

    return _sse_response(event_stream())
