import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import daily_quota
import db
import telemetry
from auth import get_verified_user
from identity import get_anon_user_id
from image_processing.compositor import compose_meme
from nlp.text_moderation import CATEGORY_DAILY_LIMIT, CATEGORY_RATE_LIMITED, moderate_text
from notices import (
    BUSY_MESSAGE,
    DAILY_BUDGET_MESSAGE,
    REASON_BUSY,
    REASON_SITE_BUDGET,
    REASON_VISITOR_LIMIT,
    visitor_limit_message,
)
from rate_limit import limiter
from schemas import MemeGenerationRequest, MemeGenerationResponse
from visitor import identify

router = APIRouter()

_GENERIC_CAPTION_REFUSAL = "That caption couldn't be used — try different text."


def _notice(status_code: int, reason: str, message: str) -> JSONResponse:
    """A "can't make that right now" answer (notices.py). `detail` is what
    every error from this API carries, so a client that knows nothing about
    reasons still shows the message."""
    return JSONResponse(status_code=status_code, content={"detail": message, "reason": reason})


@router.post("/", response_model=MemeGenerationResponse)
@limiter.limit("20/minute")
async def generate(request: Request, body: MemeGenerationRequest):
    """
    On-demand meme generation endpoint — Make's manual template+caption
    picker.

    Accepts a template_id and a dict of label→text pairs matching
    the template's TextBoxConfig labels (e.g. {"rejected_option": "...", "approved_option": "..."}).

    Unlike Chat/Lore, these captions never pass through an LLM before
    landing on a public meme, so they go through nlp.text_moderation first
    — the text equivalent of uploads/safe_ingest's image moderation gate.
    Fails closed: a moderation-unavailable result blocks the request the
    same as an actual unsafe classification (never echoes the category).
    A check the provider was too rate limited to run blocks the request
    too, but says so (busy, or the day's budget used up) rather than
    blaming the caption.

    Stamps identity + surface="make" on the resulting meme the same way
    chat.py/lore.py do (was missing entirely before — Make usage was
    invisible to Arc's stats and to "Forget me", since nothing tied a
    Make-generated meme to any user at all).

    A Make meme counts toward the visitor's daily allowance like any other
    (daily_quota.py): its caption check is a model call too. The allowance
    is taken before that call and handed back if no meme comes out.
    """
    reservation = daily_quota.reserve(identify(request), 1)
    if not reservation.granted:
        current = reservation.allowance_now()
        return _notice(
            429,
            REASON_VISITOR_LIMIT,
            visitor_limit_message(
                current.limit or 0, network=current.limited_by == daily_quota.LIMITED_BY_ADDRESS
            ),
        )
    made = 0
    try:
        response = await _generate(request, body)
        if isinstance(response, MemeGenerationResponse):
            made = 1
        return response
    finally:
        reservation.settle(made)


async def _generate(request: Request, body: MemeGenerationRequest) -> MemeGenerationResponse | JSONResponse:
    combined_text = "\n".join(body.texts.values())
    moderation = await moderate_text(combined_text)
    if not moderation.passed:
        if moderation.category == CATEGORY_DAILY_LIMIT:
            return _notice(503, REASON_SITE_BUDGET, DAILY_BUDGET_MESSAGE)
        if moderation.category == CATEGORY_RATE_LIMITED:
            return _notice(503, REASON_BUSY, BUSY_MESSAGE)
        raise HTTPException(status_code=400, detail=_GENERIC_CAPTION_REFUSAL)

    try:
        start = time.monotonic()
        saved = await compose_meme(
            template_id=body.template_id,
            texts=body.texts,
        )
        telemetry.record_meme_generation("make", time.monotonic() - start)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    telemetry.record_template_selection(body.template_id)
    anon_user_id = get_anon_user_id(request)
    verified = await get_verified_user(request)
    await db.insert_meme(
        meme_id=saved.meme_id,
        url=saved.url,
        template_id=body.template_id,
        mode="make",
        anon_user_id=anon_user_id,
        surface="make",
        user_id=verified.user_id if verified else None,
    )

    return MemeGenerationResponse(
        meme_url=saved.url,
        template_id=body.template_id,
        texts=body.texts,
    )

