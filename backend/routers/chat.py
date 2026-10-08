"""
POST /chat/       — Chat surface (text), returns Server-Sent Events.
POST /chat/image/ — Chat surface multimodal (image-as-context or canvas, 1+ photos), same SSE contract.

Growth Phase D split: Chat and Lore are now genuinely separate endpoints
(/chat/ here, /lore/ in routers/lore.py) with their own request models, but
they share this module's streaming core via the `handle_text_stream` /
`handle_image_stream` entry helpers (lore.py imports them). The only
difference is which controls each surface exposes (Lore adds meme_count +
remember_lore) and the `surface` value ("chat"/"lore") the endpoint stamps
onto every db.insert_meme — which is what makes Arc's chat/lore/make split
real (routers/generate.py stamps "make" the same way; routers/discord.py
stamps "discord", which counts toward Arc's total/aura but is intentionally
left out of the three-way split shown to the user).

Both surfaces' context-mode path flows through the same batch pipeline
(_stream_batch): a submission resolves into 1..N distinct "situations"
(nlp/segmentation.py's resolve_contexts — a no-op fast path for the common
case of one short message or one photo), and each situation is rendered into
its own meme via _stream_chat_turn, sharing one HTTP response/SSE stream. The
canvas-mode path (Mode 2 — the user's own photo becomes the meme, not a
catalog template) instead flows through _stream_canvas_batch, captioning each
surviving photo directly.

SSE event stream:
  {"type": "plan",     "situations": [...], "total": N}   — only when N > 1; also carries
                       "take_of": [null, ..., 0] when some entries are another take on an
                       earlier moment rather than a moment of their own
  {"type": "thinking", "stage": "looking",    "message": "..."}   — photo uploads only, sent first
  {"type": "thinking", "stage": "analyzing",  "index": 0, "total": 1, "message": "..."}
  {"type": "thinking", "stage": "rendering",  "index": 0, "total": 1, "template_id": "...", "message": "..."}
  {"type": "done",     "index": 0, "total": 1, "conversation_id": "...", "message": {...}, "template_used": "...", "fallback": false}
                       — plus "take_of": <index> on a meme that is another take
  {"type": "batch_done", "total": 1, "succeeded": 1}
  {"type": "error",    "index": 0, "total": 1, "message": "..."}
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

import db
import telemetry
from auth import get_verified_user
from config import get_settings
from identity import get_anon_user_id
from image_processing.compositor import compose_meme, compose_meme_on_image
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import is_daily_budget_fallback, is_fallback, parse_intent
from nlp.lexicon import schedule_lexicon_extraction
from nlp.segmentation import resolve_contexts
from nlp.vision import (
    VisionBusy,
    VisionOutOfBudget,
    describe_image,
    generate_canvas_captions,
    infer_mode,
)
from rate_limit import limiter
from schemas import ChatMessage, ChatRequest, ChatResponse, SegmentedContext, VisionDescription
from uploads.safe_ingest import (
    CleanImage,
    ModerationBusy,
    ModerationOutOfBudget,
    ModerationRejected,
    UploadRejected,
    safe_ingest,
)
from vector_db.chroma_client import log_usage

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERIC_UPLOAD_REFUSAL = "That image couldn't be processed — try a different one."
_DESCRIBE_IN_WORDS_PROMPT = (
    "I couldn't quite look at that image right now — mind describing the "
    "situation in words instead?"
)
# A call stayed rate limited through its retries. Nothing is wrong with the
# photo or caption, so this must not read as a refusal of it. For the
# provider's per-minute limit only.
BUSY_MESSAGE = "MemeGPT is busy, try again in a minute."
# The provider's daily limit: a minute will not help, and the canned
# fallback meme would say nothing about why. Owner's wording.
DAILY_BUDGET_MESSAGE = (
    "MemeGPT runs on a free daily AI budget, and today's is used up. "
    "It refills gradually, so try again in a few hours."
)
# Marks the error event that carries DAILY_BUDGET_MESSAGE, so a batch can
# stop there instead of failing the same way once per remaining meme.
_DAILY_BUDGET_REASON = "daily_budget"


def _vision_busy_message(results: list) -> str:
    """Which of the two messages a set of failed photo calls gets. One call
    stopped by the daily limit is enough: trying again in a minute would
    not help the others either, they share the model."""
    if any(isinstance(r, VisionOutOfBudget) for r in results):
        return DAILY_BUDGET_MESSAGE
    return BUSY_MESSAGE


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


_TITLE_MAX_CHARS = 48

_NO_FRESH_TEMPLATE_FOR_TAKE = (
    "MemeGPT couldn't find a different template for another take, so that one was skipped."
)


def _auto_title(text: str) -> str:
    """Growth Phase H, Stage 3 — plain truncation, not an LLM call: matches
    this codebase's cost-consciousness (segmentation's zero-LLM fast path
    for the common case) and avoids a new failure mode (LLM down -> forever-
    untitled) for a short sidebar label that doesn't need semantic quality."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _TITLE_MAX_CHARS:
        return collapsed
    return collapsed[:_TITLE_MAX_CHARS].rsplit(" ", 1)[0] + "…"


async def _stream_chat_turn(
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
    index: int = 0,
    total: int = 1,
    conversation_row_id: str | None = None,
    take_of: int | None = None,
    exclude_templates: list[str] | None = None,
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
    as empty.

    conversation_row_id (Growth Phase H, Stage 3, optional): an already
    ownership-checked persisted conversation (see handle_text_stream) — the
    user message is written HERE, before generation even starts, so a
    downstream failure (parse_intent/compose_meme raising) still leaves the
    user's own message in their history rather than silently dropping it.

    take_of / exclude_templates: set together when this turn is another take
    on a moment an earlier turn in the same batch already rendered (see
    _stream_batch). exclude_templates are the templates that moment has
    already used; the take is dropped rather than rendered if the pick is
    one of them anyway, which only parse_intent's hard fallback can cause."""
    yield {
        "type": "thinking",
        "stage": "analyzing",
        "index": index,
        "total": total,
        "message": "Reading your vibe...",
    }

    # A take repeats a situation whose user row the first turn already wrote.
    if conversation_row_id and ctx and ctx.user_id and take_of is None:
        await db.insert_message(conversation_row_id, "user", user_message)

    start = time.monotonic()
    try:
        intent = await _resolve_intent_for_turn(user_message, conversation_id, ctx, exclude_templates)
    except Exception as exc:
        yield {"type": "error", "index": index, "total": total, "message": str(exc)}
        return

    if is_daily_budget_fallback(intent):
        yield {
            "type": "error",
            "index": index,
            "total": total,
            "message": DAILY_BUDGET_MESSAGE,
            "reason": _DAILY_BUDGET_REASON,
        }
        return

    if exclude_templates and intent.template_id in exclude_templates:
        yield {"type": "error", "index": index, "total": total, "message": _NO_FRESH_TEMPLATE_FOR_TAKE}
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
        response = await _render_and_record_turn(
            intent, user_message, conversation_id, ctx, surface, conversation_row_id
        )
    except FileNotFoundError as exc:
        yield {"type": "error", "index": index, "total": total, "message": f"Template not found: {exc}"}
        return
    telemetry.record_meme_generation(surface, time.monotonic() - start)

    done = {"type": "done", "index": index, "total": total, **response.model_dump(mode="json")}
    if take_of is not None:
        done["take_of"] = take_of
    yield done


async def _resolve_intent_for_turn(
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    exclude_templates: list[str] | None = None,
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

    # Passed only when there is something to exclude, so the common call
    # keeps the exact shape it has always had.
    hard_exclusion = {"exclude_templates": exclude_templates} if exclude_templates else {}
    return await parse_intent(
        user_message,
        avoid_templates=avoid,
        loved_templates=ctx.loved_templates if ctx else None,
        hated_templates=ctx.hated_templates if ctx else None,
        lexicon=ctx.lexicon if ctx else None,
        **hard_exclusion,
    )


async def _render_and_record_turn(
    intent,
    user_message: str,
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
    conversation_row_id: str | None = None,
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

    telemetry.record_template_selection(intent.template_id)
    log_usage(intent.template_id)
    await db.insert_meme(
        meme_id=saved.meme_id,
        url=saved.url,
        template_id=intent.template_id,
        mode="context",
        anon_user_id=ctx.anon_user_id if ctx else None,
        surface=surface,
        user_id=ctx.user_id if ctx else None,
    )

    if conversation_row_id and ctx and ctx.user_id:
        await db.insert_message(conversation_row_id, "assistant", user_message, meme_id=saved.meme_id)
        await db.set_conversation_title_if_unset(conversation_row_id, _auto_title(user_message))

    reply = ChatMessage(role="assistant", content=user_message, meme_url=saved.url, meme_id=saved.meme_id)
    return ChatResponse(
        conversation_id=conversation_id,
        message=reply,
        template_used=intent.template_id,
        fallback=is_fallback(intent),
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
    is just both halves back to back with nothing in between. Never passes a
    conversation_row_id — Discord has no persisted-conversation concept."""
    start = time.monotonic()
    intent = await _resolve_intent_for_turn(user_message, conversation_id, ctx)
    response = await _render_and_record_turn(intent, user_message, conversation_id, ctx, surface)
    telemetry.record_meme_generation(surface, time.monotonic() - start)
    return response


async def _stream_batch(
    contexts: list[SegmentedContext],
    conversation_id: str,
    ctx: db.PersonalizationContext | None = None,
    surface: str | None = None,
    conversation_row_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Runs each context through _stream_chat_turn IN SEQUENCE (not
    parallel — this lets each context's avoid_templates see the previous
    context's just-picked template via conversation_store's recency
    tracking, so a batch naturally gets diverse templates for free),
    yielding every event as it happens so memes appear progressively rather
    than all at once at the end.

    A context with take_of set is another take on an earlier moment in the
    same batch, not a moment of its own. The plan says so instead of
    printing that moment's text a second time, and the take is rendered with
    every template the moment has already used ruled out — the recency
    nudge above is a request to the model, this is a guarantee.

    The batch ends early at the first meme the model's daily budget could
    not cover: the ones after it would fail the same way."""
    total = len(contexts)
    if total > 1:
        # "Plan theater" for a single meme is pointless — only worth
        # announcing when there's actually more than one situation to work
        # through, regardless of whether that came from the zero-LLM fast
        # path (which never returns more than one) or segmentation itself
        # concluding there's only one distinct moment.
        plan: dict = {
            "type": "plan",
            "situations": [
                c.situation if c.take_of is None else f"Another take on moment {c.take_of + 1}"
                for c in contexts
            ],
            "total": total,
        }
        if any(c.take_of is not None for c in contexts):
            plan["take_of"] = [c.take_of for c in contexts]
        yield _sse(plan)
    succeeded = 0
    templates_by_moment: dict[int, list[str]] = {}
    out_of_budget = False
    for i, context in enumerate(contexts):
        if out_of_budget:
            break
        moment = i if context.take_of is None else context.take_of
        async for event in _stream_chat_turn(
            context.situation, conversation_id, ctx, surface, index=i, total=total,
            conversation_row_id=conversation_row_id,
            take_of=context.take_of,
            exclude_templates=list(templates_by_moment.get(moment, [])) if context.take_of is not None else None,
        ):
            if event.get("type") == "done":
                succeeded += 1
                if event.get("template_used"):
                    templates_by_moment.setdefault(moment, []).append(event["template_used"])
            elif event.get("reason") == _DAILY_BUDGET_REASON:
                out_of_budget = True
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
    user_id: str | None = None,
    conversation_row_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Mode 2 (canvas) — mirrors _stream_chat_turn's shape but skips RAG,
    parse_intent, add_turn, and log_usage entirely: there's no template_id
    (the user's own photo IS the meme), no repetition to avoid (each meme
    is on a unique photo), and log_usage is keyed by catalog template_id in
    ChromaDB, which a custom photo isn't part of. template_used stays None.
    db.insert_meme() (Growth Phase B) is NOT skipped, unlike the above —
    the durable memes table tracks every meme regardless of mode, since
    canvas-mode memes get /m/{id} share pages too.

    conversation_row_id (Growth Phase H, Stage 3): only writes the
    ASSISTANT message here — the shared user message (if any) is written
    once by the caller (_stream_canvas_batch), not once per photo."""
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
        user_id=user_id,
    )

    # The captions themselves are this meme's "situation" for feedback-
    # keying purposes (examples_store.upsert_example hashes on this text) —
    # distinct captions per photo avoid the same collision fixed for Mode 1.
    situation_text = f"{texts.get('top_text', '')} {texts.get('bottom_text', '')}".strip()

    if conversation_row_id and user_id:
        await db.insert_message(conversation_row_id, "assistant", situation_text, meme_id=saved.meme_id)
        await db.set_conversation_title_if_unset(conversation_row_id, _auto_title(situation_text))

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
    user_id: str | None = None,
    conversation_row_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Mode 2 (canvas) batch — captions each surviving photo directly via
    generate_canvas_captions(), never touching resolve_contexts/parse_intent
    at all (there's no template to pick). generate_canvas_captions() returns
    None on failure, filtered out below, and raises only VisionBusy (rate
    limited past its retries): photos that got captions still become memes,
    and if none did the reply says busy. meme_count is intentionally ignored: its
    semantics don't transfer (segmentation splits one input into N
    synthetic situations; canvas mode's count is already fixed by how many
    photos survived ingestion)."""
    if conversation_row_id and user_id and message:
        # Written once for the whole batch — every photo shares this same
        # accompanying text, unlike _stream_canvas_turn's per-photo reply.
        await db.insert_message(conversation_row_id, "user", message)

    caption_results = await asyncio.gather(
        *[generate_canvas_captions(ci.image, message) for ci in clean_images],
        return_exceptions=True,
    )
    pairs = [
        (ci, captions) for ci, captions in zip(clean_images, caption_results) if isinstance(captions, dict)
    ]

    if not pairs:
        if any(isinstance(r, VisionBusy) for r in caption_results):
            yield _sse({"type": "error", "message": _vision_busy_message(caption_results)})
            return
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
            clean_image.image, captions, conversation_id, anon_user_id, surface,
            index=i, total=total, user_id=user_id, conversation_row_id=conversation_row_id,
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


async def _resolve_conversation_row_id(
    conversation_row_id_in: str | None, user_id: str | None
) -> str | None:
    """Growth Phase H, Stage 3 — the one ownership check per request. A
    client-supplied id that doesn't verify (wrong owner, doesn't exist, no
    signed-in user at all) is silently ignored, not an error: the turn
    just proceeds without persistence, exactly like today's anonymous
    behavior, rather than failing an otherwise-normal chat request over a
    stale or forged id."""
    if not conversation_row_id_in or not user_id:
        return None
    owner = await db.fetch_conversation_owner(conversation_row_id_in)
    return conversation_row_id_in if owner == user_id else None


async def handle_text_stream(
    request: Request,
    message_in: str,
    conversation_id_in: str | None,
    meme_count: int | None,
    remember_lore: bool,
    surface: str,
    conversation_row_id_in: str | None = None,
) -> StreamingResponse:
    """Shared text-turn core for both /chat/ and /lore/ (Growth Phase D).
    Streams SSE events as one or more memes are generated — resolve_contexts
    decides (with zero added latency for a normal short message) whether this
    is one situation or several. Chat calls this with meme_count=None,
    remember_lore=False, surface="chat"; Lore passes its real values and
    surface="lore"."""
    anon_user_id = get_anon_user_id(request)
    verified = await get_verified_user(request)
    user_id = verified.user_id if verified else None
    ctx = await db.fetch_personalization(anon_user_id, user_id)
    conversation_id = conversation_id_in or ""
    conversation_row_id = await _resolve_conversation_row_id(conversation_row_id_in, user_id)
    message = _clamp_dump_text(message_in) or ""
    if remember_lore:
        schedule_lexicon_extraction(anon_user_id, message, user_id, conversation_row_id)
    contexts = await resolve_contexts(message, None, meme_count, lexicon=ctx.lexicon)
    return _sse_response(
        _stream_batch(contexts, conversation_id, ctx, surface, conversation_row_id)
    )


async def handle_image_stream(
    request: Request,
    images: list[UploadFile],
    message_in: str | None,
    conversation_id_in: str | None,
    meme_count: int | None,
    mode: str | None,
    remember_lore: bool,
    surface: str,
    conversation_row_id_in: str | None = None,
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
    modes and both surfaces.

    A photo whose safety check could not be run (ModerationBusy: rate
    limited past the retries) also stops the whole request, but with "busy,
    try again in a minute" rather than a refusal, or with the daily-budget
    wording when the provider's daily limit is what stopped the check. It is never processed
    unchecked, and the photos that did pass are not turned into a partial
    result the user didn't ask for. A real refusal in the same batch wins."""
    anon_user_id = get_anon_user_id(request)
    verified = await get_verified_user(request)
    user_id = verified.user_id if verified else None
    ctx = await db.fetch_personalization(anon_user_id, user_id)
    conv_id = conversation_id_in or ""
    conversation_row_id = await _resolve_conversation_row_id(conversation_row_id_in, user_id)
    message = _clamp_dump_text(message_in)
    if remember_lore:
        schedule_lexicon_extraction(anon_user_id, message, user_id, conversation_row_id)
    if mode not in ("context", "canvas"):
        mode = None
    resolved_mode = mode or infer_mode(message)

    async def event_stream() -> AsyncGenerator[str, None]:
        settings = get_settings()
        capped_images = images[: settings.max_images_per_request]

        # Sent before any photo call: a rate-limited safety check can hold
        # this stream for most of a minute, and a connection with nothing
        # on it looks dead to whatever sits in front of the backend.
        yield _sse({
            "type": "thinking",
            "stage": "looking",
            "message": "Looking at your photo..." if len(capped_images) == 1 else "Looking at your photos...",
        })

        ingest_results = await asyncio.gather(
            *[safe_ingest(img) for img in capped_images],
            return_exceptions=True,
        )

        moderation_rejections = [r for r in ingest_results if isinstance(r, ModerationRejected)]
        if any(not isinstance(r, ModerationBusy) for r in moderation_rejections):
            yield _sse({"type": "error", "message": _GENERIC_UPLOAD_REFUSAL})
            return
        if moderation_rejections:
            out_of_budget = any(isinstance(r, ModerationOutOfBudget) for r in moderation_rejections)
            yield _sse({"type": "error", "message": DAILY_BUDGET_MESSAGE if out_of_budget else BUSY_MESSAGE})
            return

        clean_images = [r for r in ingest_results if isinstance(r, CleanImage)]

        if not clean_images:
            # All images failed non-safety validation (too big/wrong type).
            # Degrade to a text-only turn if there's accompanying text,
            # rather than hard-refusing when the user's words are still usable.
            if message:
                contexts = await resolve_contexts(message, None, meme_count, lexicon=ctx.lexicon)
                async for event in _stream_batch(contexts, conv_id, ctx, surface, conversation_row_id):
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
            async for event in _stream_canvas_batch(
                clean_images, message, conv_id, anon_user_id, surface,
                user_id=user_id, conversation_row_id=conversation_row_id,
            ):
                yield event
            return

        description_results = await asyncio.gather(
            *[describe_image(ci.image, user_text=message) for ci in clean_images],
            return_exceptions=True,
        )
        descriptions = [d.situation for d in description_results if isinstance(d, VisionDescription)]

        if not descriptions:
            if any(isinstance(d, VisionBusy) for d in description_results):
                yield _sse({"type": "error", "message": _vision_busy_message(description_results)})
                return
            # Every vision call failed (VisionUnavailable) — graceful
            # degrade, a normal assistant reply, not a hard error.
            reply = ChatMessage(role="assistant", content=_DESCRIBE_IN_WORDS_PROMPT)
            response = ChatResponse(conversation_id=conv_id, message=reply)
            yield _sse({"type": "done", **response.model_dump(mode="json")})
            return

        contexts = await resolve_contexts(message, descriptions, meme_count, lexicon=ctx.lexicon)
        async for event in _stream_batch(contexts, conv_id, ctx, surface, conversation_row_id):
            yield event

    return _sse_response(event_stream())


@router.post("/")
@limiter.limit("20/minute")
async def chat(request: Request, body: ChatRequest):
    """Chat surface — minimal chrome, always auto-detects meme count, no Lore
    lexicon. Delegates to the shared core with surface="chat"."""
    return await handle_text_stream(
        request, body.message, body.conversation_id,
        meme_count=None, remember_lore=False, surface="chat",
        conversation_row_id_in=body.conversation_row_id,
    )


@router.post("/image/")
@limiter.limit(get_settings().upload_rate_limit)
async def chat_with_image(
    request: Request,  # required by slowapi's key_func, unused otherwise
    images: list[UploadFile] = File(...),
    message: str | None = Form(None),
    conversation_id: str | None = Form(None),
    mode: str | None = Form(None),
    conversation_row_id: str | None = Form(None),
):
    """Chat surface multimodal. No meme_count / remember_lore (Lore-only)."""
    return await handle_image_stream(
        request, images, message, conversation_id,
        meme_count=None, mode=mode, remember_lore=False, surface="chat",
        conversation_row_id_in=conversation_row_id,
    )
