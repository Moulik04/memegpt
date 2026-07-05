"""
POST /chat/       — main conversational endpoint (text), returns Server-Sent Events.
POST /chat/image/ — multimodal endpoint (image-as-context or canvas mode, 1+ photos), same SSE contract.

/chat/ and /chat/image/'s context-mode path both flow through the same
batch pipeline (_stream_batch): a submission resolves into 1..N distinct
"situations" (nlp/segmentation.py's resolve_contexts — a no-op fast path
for the common case of one short message or one photo), and each situation
is rendered into its own meme via _stream_chat_turn, sharing one HTTP
response/SSE stream. /chat/image/'s canvas-mode path (Mode 2 — the user's
own photo becomes the meme, not a catalog template) instead flows through
_stream_canvas_batch, captioning each surviving photo directly.

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
from PIL import Image

from config import get_settings
from image_processing.compositor import compose_meme, compose_meme_on_image
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import parse_intent
from nlp.segmentation import resolve_contexts
from nlp.vision import describe_image, generate_canvas_captions, infer_mode
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
    log_usage -> done sequence for ONE situation (Mode 1: context). Yields
    raw event dicts — the caller (_stream_batch) serializes them to SSE
    strings, so index/total can be merged in centrally without every event
    constructor repeating it. `content` on the reply carries the situation
    text itself (previously always ""), which the frontend uses to key
    per-meme feedback correctly when several memes in one batch share a
    single preceding user bubble."""
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


async def _stream_canvas_turn(
    image: Image.Image,
    texts: dict[str, str],
    conversation_id: str,
    index: int = 0,
    total: int = 1,
) -> AsyncGenerator[dict, None]:
    """Mode 2 (canvas) — mirrors _stream_chat_turn's shape but skips RAG,
    parse_intent, add_turn, and log_usage entirely: there's no template_id
    (the user's own photo IS the meme), no repetition to avoid (each meme
    is on a unique photo), and log_usage is keyed by catalog template_id in
    ChromaDB, which a custom photo isn't part of. template_used stays None."""
    yield {
        "type": "thinking",
        "stage": "rendering",
        "index": index,
        "total": total,
        "message": "Captioning your photo...",
    }

    try:
        meme_url = await compose_meme_on_image(image, texts)
    except Exception as exc:
        yield {"type": "error", "index": index, "total": total, "message": str(exc)}
        return

    # The captions themselves are this meme's "situation" for feedback-
    # keying purposes (examples_store.upsert_example hashes on this text) —
    # distinct captions per photo avoid the same collision fixed for Mode 1.
    situation_text = f"{texts.get('top_text', '')} {texts.get('bottom_text', '')}".strip()
    reply = ChatMessage(role="assistant", content=situation_text, meme_url=meme_url)
    response = ChatResponse(
        conversation_id=conversation_id,
        message=reply,
        template_used=None,
    )

    yield {"type": "done", "index": index, "total": total, **response.model_dump(mode="json")}


async def _stream_canvas_batch(
    clean_images: list[CleanImage],
    message: str | None,
    conversation_id: str,
) -> AsyncGenerator[str, None]:
    """Mode 2 (canvas) batch — captions each surviving photo directly via
    generate_canvas_captions(), never touching resolve_contexts/parse_intent
    at all (there's no template to pick). generate_canvas_captions() never
    raises, so no return_exceptions=True needed here — it returns None on
    failure, filtered out below. meme_count is intentionally ignored: its
    semantics don't transfer (segmentation splits one input into N
    synthetic situations; canvas mode's count is already fixed by how many
    photos survived ingestion)."""
    caption_results = await asyncio.gather(
        *[generate_canvas_captions(ci.image, message) for ci in clean_images]
    )
    pairs = [
        (ci, captions) for ci, captions in zip(clean_images, caption_results) if captions is not None
    ]

    if not pairs:
        # Every canvas-caption call failed — graceful degrade, a normal
        # assistant reply, not a hard error.
        reply = ChatMessage(role="assistant", content=_DESCRIBE_IN_WORDS_PROMPT)
        response = ChatResponse(conversation_id=conversation_id, message=reply)
        yield _sse({"type": "done", **response.model_dump(mode="json")})
        return

    total = len(pairs)
    succeeded = 0
    for i, (clean_image, captions) in enumerate(pairs):
        async for event in _stream_canvas_turn(
            clean_image.image, captions, conversation_id, index=i, total=total
        ):
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
    mode: str | None = Form(None),
):
    """
    Uploads 1+ photos and generates memes from them, in one of two modes:

    Mode 1 (context, default): describes each photo via the vision layer,
    resolves the descriptions (+ any user text) into 1..N situations, and
    feeds each into the same _stream_batch used by /chat/ — the photo
    informs which CATALOG template gets picked.

    Mode 2 (canvas): the user's own photo becomes the meme directly,
    captioned top/bottom, no catalog template involved. Selected via
    keyword inference on `message` (nlp.vision.infer_mode — e.g. "make
    this a meme") or the explicit `mode` override below.

    ALL uploaded images pass through uploads/safe_ingest.safe_ingest() —
    never bypass it. A content-moderation failure on ANY image aborts the
    WHOLE request with today's generic refusal (a moderation hit is an
    adversarial signal, unlike a size/type failure, and skip-and-continue
    would leak a per-image "this one got silently dropped" signal that
    uploads/moderation.py's category-never-echoed invariant exists to
    prevent). A non-safety UploadRejected on one image in a batch just
    drops that image and continues with the rest. This gate is identical
    for both modes.
    """
    conv_id = conversation_id or ""
    if mode not in ("context", "canvas"):
        mode = None
    resolved_mode = mode or infer_mode(message)

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

        if resolved_mode == "canvas":
            async for event in _stream_canvas_batch(clean_images, message, conv_id):
                yield event
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
