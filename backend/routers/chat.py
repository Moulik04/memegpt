"""
POST /chat/       — Chat surface (text), returns Server-Sent Events.
POST /chat/image/ — Chat surface multimodal (image-as-context or canvas, 1+ photos), same SSE contract.

Growth Phase D split: Chat and Lore are now genuinely separate endpoints
(/chat/ here, /lore/ in routers/lore.py) with their own request models, but
they share this module's streaming core via the `handle_text_stream` /
`handle_image_stream` entry helpers (lore.py imports them). The only
difference is which controls each surface exposes (Lore adds meme_count +
remember_lore) and the `surface` value ("chat"/"lore") the endpoint stamps
onto every db.insert_meme — which is what makes Arc's Chat-vs-Lore split real.

Both surfaces' context-mode path flows through the same batch pipeline
(_stream_batch): a submission resolves into 1..N distinct "situations"
(nlp/segmentation.py's resolve_contexts — a no-op fast path for the common
case of one short message or one photo), and each situation is rendered into
its own meme via _stream_chat_turn, sharing one HTTP response/SSE stream. The
canvas-mode path (Mode 2 — the user's own photo becomes the meme, not a
catalog template) instead flows through _stream_canvas_batch, captioning each
surviving photo directly.

SSE event stream:
  {"type": "plan",     "situations": [...], "total": N}   — only when N > 1
  {"type": "thinking", "stage": "analyzing",  "index": 0, "total": 1, "message": "..."}
  {"type": "thinking", "stage": "rendering",  "index": 0, "total": 1, "template_id": "...", "message": "..."}
  {"type": "done",     "index": 0, "total": 1, "conversation_id": "...", "message": {...}, "template_used": "..."}
  {"type": "batch_done", "total": 1, "succeeded": 1}
  {"type": "error",    "index": 0, "total": 1, "message": "..."}
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

import db
from config import get_settings
from identity import get_anon_user_id
from image_processing.compositor import compose_meme, compose_meme_on_image
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import parse_intent
from nlp.lexicon import schedule_lexicon_extraction
from nlp.segmentation import resolve_contexts
from nlp.vision import describe_image, generate_canvas_captions, infer_mode
from rate_limit import limiter
from schemas import ChatMessage, ChatRequest, ChatResponse, VisionDescription
from uploads.safe_ingest import CleanImage, ModerationRejected, UploadRejected, safe_ingest
from vector_db.chroma_client import log_usage

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERIC_UPLOAD_REFUSAL = "That image couldn't be processed — try a different one."
_DESCRIBE_IN_WORDS_PROMPT = (
    "I couldn't quite look at that image right now — mind describing the "
    "situation in words instead?"
)


def _upload_rejection_message(reason: str) -> str:
    """Maps a non-safety UploadRejected.reason to specific, friendly text.

    Safe to be specific here because these reasons (size/type/dimensions)
    carry no adversarial signal — unlike ModerationRejected, whose category
    is never echoed (see uploads/moderation.py) to avoid handing a probing
    oracle to anyone testing the content classifier."""
    settings = get_settings()
    max_mb = settings.max_image_bytes // (1024 * 1024)
    messages = {
        "file_too_large": f"That image is over {max_mb}MB — try a smaller one.",
        "unrecognized_file_type": "That file isn't a supported image format — try a JPEG, PNG, or WEBP.",
        "decompression_bomb": "That image's dimensions are too large to process — try a smaller one.",
        "dimensions_too_large": "That image's dimensions are too large to process — try a smaller one.",
        "invalid_image": "That file couldn't be read as an image — it may be corrupted.",
    }
    return messages.get(reason, _GENERIC_UPLOAD_REFUSAL)


def _clamp_dump_text(text: str | None) -> str | None:
    """Lore's big-paste ceiling (max_dump_chars) — truncates rather than
    rejects, since a partial highlight reel from the first N characters is
    still useful, unlike hard-refusing a slightly-too-long paste."""
    if text is None:
        return None
    settings = get_settings()
    if len(text) > settings.max_dump_chars:
        logger.debug(
            "dump_text_clamped",
            extra={"original_len": len(text), "clamped_len": settings.max_dump_chars},
        )
        return text[: settings.max_dump_chars]
    return text


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_chat_turn(
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
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
    single preceding user bubble.

    ctx (Growth Phase C, optional): this request's anon-user personalization
    bundle, fetched ONCE per batch by the caller since it doesn't change
    turn-to-turn (unlike the in-memory recent-templates lookup below, which
    does). None when there's no anon id — every field on it is then treated
    as empty."""
    yield {
        "type": "thinking",
        "stage": "analyzing",
        "index": index,
        "total": total,
        "message": "Reading your vibe...",
    }

    try:
        intent = await _resolve_intent_for_turn(user_message, conversation_id, ctx)
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
        response = await _render_and_record_turn(intent, user_message, conversation_id, ctx, surface)
    except FileNotFoundError as exc:
        yield {"type": "error", "index": index, "total": total, "message": f"Template not found: {exc}"}
        return

    yield {"type": "done", "index": index, "total": total, **response.model_dump(mode="json")}


async def _resolve_intent_for_turn(
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
):
    """avoid_templates merge + parse_intent — the first half of a turn,
    extracted so both the SSE path (_stream_chat_turn) and the plain
    synchronous path (generate_single_meme, used by routers/discord.py)
    share it without either duplicating the merge logic."""
    # In-memory, per-conversation half of avoid_templates (updates turn-to-
    # turn within this batch) merged with the cross-session, DB-backed half
    # (fetched once for the whole batch) — in-memory first since it's the
    # freshest signal, deduped preserving order.
    recent = get_recent_templates(conversation_id, n=5)
    cross_session = ctx.avoid_templates if ctx else []
    avoid = list(dict.fromkeys(recent + cross_session))[:5]

    return await parse_intent(
        user_message,
        avoid_templates=avoid,
        loved_templates=ctx.loved_templates if ctx else None,
        hated_templates=ctx.hated_templates if ctx else None,
        lexicon=ctx.lexicon if ctx else None,
    )


async def _render_and_record_turn(
    intent,
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
) -> ChatResponse:
    """compose_meme -> log_usage/db.insert_meme -> build ChatResponse — the
    second half of a turn, given an already-resolved IntentResponse. Raises
    FileNotFoundError on a missing template (the realistic failure mode);
    _stream_chat_turn catches it into an SSE error event, generate_single_meme
    lets it propagate to its own caller."""
    saved = await compose_meme(
        template_id=intent.template_id,
        texts=intent.texts,
    )

    add_turn(conversation_id, intent.template_id)

    log_usage(
        template_id=intent.template_id,
        top_text=next(iter(intent.texts.values()), ""),
        bottom_text=list(intent.texts.values())[-1] if len(intent.texts) > 1 else "",
        conversation_id=conversation_id,
    )
    await db.insert_meme(
        meme_id=saved.meme_id,
        url=saved.url,
        template_id=intent.template_id,
        mode="context",
        anon_user_id=ctx.anon_user_id if ctx else None,
        surface=surface,
    )

    reply = ChatMessage(role="assistant", content=user_message, meme_url=saved.url, meme_id=saved.meme_id)
    return ChatResponse(
        conversation_id=conversation_id,
        message=reply,
        template_used=intent.template_id,
    )


async def generate_single_meme(
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
) -> ChatResponse:
    """Plain non-streaming entry point for a single meme — routers/discord.py's
    one-shot /meme command uses this directly (no SSE, no progress events,
    just await and get a ChatResponse back or an exception). Chat/Lore's SSE
    path (_stream_chat_turn above) calls the same two halves directly
    instead, so it can yield a 'rendering' progress event between them; this
    is just both halves back to back with nothing in between."""
    intent = await _resolve_intent_for_turn(user_message, conversation_id, ctx)
    return await _render_and_record_turn(intent, user_message, conversation_id, ctx, surface)


async def _stream_batch(
    situations: list[str],
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
) -> AsyncGenerator[str, None]:
    """Runs each situation through _stream_chat_turn IN SEQUENCE (not
    parallel — this lets each context's avoid_templates see the previous
    context's just-picked template via conversation_store's recency
    tracking, so repeated/padded situations naturally get diverse templates
    for free), yielding every event as it happens so memes appear
    progressively rather than all at once at the end."""
    total = len(situations)
    if total > 1:
        # "Plan theater" for a single meme is pointless — only worth
        # announcing when there's actually more than one situation to work
        # through, regardless of whether that came from the zero-LLM fast
        # path (which never returns more than one) or segmentation itself
        # concluding there's only one distinct moment.
        yield _sse({"type": "plan", "situations": situations, "total": total})
    succeeded = 0
    for i, situation in enumerate(situations):
        async for event in _stream_chat_turn(
            situation, conversation_id, ctx, surface, index=i, total=total
        ):
            if event.get("type") == "done":
                succeeded += 1
            yield _sse(event)
    yield _sse({"type": "batch_done", "total": total, "succeeded": succeeded})


async def _stream_canvas_turn(
    image: Image.Image,
    texts: dict[str, str],
    conversation_id: str,
    anon_user_id: str | None = None,
    surface: str | None = None,
    index: int = 0,
    total: int = 1,
) -> AsyncGenerator[dict, None]:
    """Mode 2 (canvas) — mirrors _stream_chat_turn's shape but skips RAG,
    parse_intent, add_turn, and log_usage entirely: there's no template_id
    (the user's own photo IS the meme), no repetition to avoid (each meme
    is on a unique photo), and log_usage is keyed by catalog template_id in
    ChromaDB, which a custom photo isn't part of. template_used stays None.
    db.insert_meme() (Growth Phase B) is NOT skipped, unlike the above —
    the durable memes table tracks every meme regardless of mode, since
    canvas-mode memes get /m/{id} share pages too."""
    yield {
        "type": "thinking",
        "stage": "rendering",
        "index": index,
        "total": total,
        "message": "Captioning your photo...",
    }

    try:
        saved = await compose_meme_on_image(image, texts)
    except Exception as exc:
        yield {"type": "error", "index": index, "total": total, "message": str(exc)}
        return

    await db.insert_meme(
        meme_id=saved.meme_id,
        url=saved.url,
        template_id=None,
        mode="canvas",
        anon_user_id=anon_user_id,
        surface=surface,
    )

    # The captions themselves are this meme's "situation" for feedback-
    # keying purposes (examples_store.upsert_example hashes on this text) —
    # distinct captions per photo avoid the same collision fixed for Mode 1.
    situation_text = f"{texts.get('top_text', '')} {texts.get('bottom_text', '')}".strip()
    reply = ChatMessage(role="assistant", content=situation_text, meme_url=saved.url, meme_id=saved.meme_id)
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
    anon_user_id: str | None = None,
    surface: str | None = None,
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
            clean_image.image, captions, conversation_id, anon_user_id, surface, index=i, total=total
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


async def handle_text_stream(
    request: Request,
    message_in: str,
    conversation_id_in: str | None,
    meme_count: int | None,
    remember_lore: bool,
    surface: str,
) -> StreamingResponse:
    """Shared text-turn core for both /chat/ and /lore/ (Growth Phase D).
    Streams SSE events as one or more memes are generated — resolve_contexts
    decides (with zero added latency for a normal short message) whether this
    is one situation or several. Chat calls this with meme_count=None,
    remember_lore=False, surface="chat"; Lore passes its real values and
    surface="lore"."""
    anon_user_id = get_anon_user_id(request)
    ctx = await db.fetch_personalization(anon_user_id)
    conversation_id = conversation_id_in or ""
    message = _clamp_dump_text(message_in) or ""
    if remember_lore:
        schedule_lexicon_extraction(anon_user_id, message)
    contexts = await resolve_contexts(message, None, meme_count, lexicon=ctx.lexicon)
    return _sse_response(_stream_batch(contexts, conversation_id, ctx, surface))


async def handle_image_stream(
    request: Request,
    images: list[UploadFile],
    message_in: str | None,
    conversation_id_in: str | None,
    meme_count: int | None,
    mode: str | None,
    remember_lore: bool,
    surface: str,
) -> StreamingResponse:
    """Shared image-turn core for both /chat/image/ and /lore/image/
    (Growth Phase D). Uploads 1+ photos and generates memes from them, in one
    of two modes:

    Mode 1 (context, default): describes each photo via the vision layer,
    resolves the descriptions (+ any user text) into 1..N situations, and
    feeds each into _stream_batch — the photo informs which CATALOG template
    gets picked.

    Mode 2 (canvas): the user's own photo becomes the meme directly,
    captioned top/bottom, no catalog template involved. Selected via keyword
    inference on `message` (nlp.vision.infer_mode — e.g. "make this a meme")
    or the explicit `mode` override.

    ALL uploaded images pass through uploads/safe_ingest.safe_ingest() —
    never bypass it. A content-moderation failure on ANY image aborts the
    WHOLE request with today's generic refusal (a moderation hit is an
    adversarial signal, unlike a size/type failure, and skip-and-continue
    would leak a per-image "this one got silently dropped" signal that
    uploads/moderation.py's category-never-echoed invariant exists to
    prevent). A non-safety UploadRejected on one image in a batch just drops
    that image and continues with the rest. This gate is identical for both
    modes and both surfaces."""
    anon_user_id = get_anon_user_id(request)
    ctx = await db.fetch_personalization(anon_user_id)
    conv_id = conversation_id_in or ""
    message = _clamp_dump_text(message_in)
    if remember_lore:
        schedule_lexicon_extraction(anon_user_id, message)
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
                contexts = await resolve_contexts(message, None, meme_count, lexicon=ctx.lexicon)
                async for event in _stream_batch(contexts, conv_id, ctx, surface):
                    yield event
                return
            # No ModerationRejected made it this far (that check already
            # returned early above), so every rejection here is a
            # non-safety UploadRejected — safe to surface the specific reason.
            upload_rejections = [r for r in ingest_results if isinstance(r, UploadRejected)]
            reason = upload_rejections[0].reason if upload_rejections else None
            message_to_show = _upload_rejection_message(reason) if reason else _GENERIC_UPLOAD_REFUSAL
            yield _sse({"type": "error", "message": message_to_show})
            return

        if resolved_mode == "canvas":
            async for event in _stream_canvas_batch(clean_images, message, conv_id, anon_user_id, surface):
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

        contexts = await resolve_contexts(message, descriptions, meme_count, lexicon=ctx.lexicon)
        async for event in _stream_batch(contexts, conv_id, ctx, surface):
            yield event

    return _sse_response(event_stream())


@router.post("/")
async def chat(request: Request, body: ChatRequest):
    """Chat surface — minimal chrome, always auto-detects meme count, no Lore
    lexicon. Delegates to the shared core with surface="chat"."""
    return await handle_text_stream(
        request, body.message, body.conversation_id,
        meme_count=None, remember_lore=False, surface="chat",
    )


@router.post("/image/")
@limiter.limit(get_settings().upload_rate_limit)
async def chat_with_image(
    request: Request,  # required by slowapi's key_func, unused otherwise
    images: list[UploadFile] = File(...),
    message: str | None = Form(None),
    conversation_id: str | None = Form(None),
    mode: str | None = Form(None),
):
    """Chat surface multimodal. No meme_count / remember_lore (Lore-only)."""
    return await handle_image_stream(
        request, images, message, conversation_id,
        meme_count=None, mode=mode, remember_lore=False, surface="chat",
    )
