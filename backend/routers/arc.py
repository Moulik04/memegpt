"""
GET /arc/       — this anon user's personal meme stats + roast copy (Growth Phase D).
POST /arc/card  — renders + persists a shareable Arc card, returns its /m/{id}.

Both private by construction: only reachable with the caller's own
X-MemeGPT-User header, no listing endpoint exists anywhere. GET /arc/ never
errors on absence (no header, no DATABASE_URL, not enough data yet) — it
always returns a valid ArcStats with has_enough=False, which the frontend
renders as the empty state rather than an error.
"""

from fastapi import APIRouter, HTTPException, Request

import db
from arc.copy import build_arc_stats
from identity import get_anon_user_id
from image_processing.compositor import compose_arc_card
from rate_limit import limiter
from schemas import ArcCardResponse, ArcStats

router = APIRouter()


async def _stats_for(request: Request, tz: str) -> ArcStats:
    anon_user_id = get_anon_user_id(request)
    if anon_user_id is None:
        return ArcStats(has_enough=False)
    raw = await db.fetch_raw_arc_stats(anon_user_id, tz=tz)
    return build_arc_stats(raw, tz=tz)


@router.get("/", response_model=ArcStats)
@limiter.limit("30/minute")
async def get_arc(request: Request, tz: str = "UTC") -> ArcStats:
    return await _stats_for(request, tz)


@router.post("/card", response_model=ArcCardResponse)
@limiter.limit("5/minute")
async def create_arc_card(request: Request, tz: str = "UTC") -> ArcCardResponse:
    """On-demand only — nothing is rendered for a user who never taps
    share. Rejects rather than rendering a hollow card for someone below
    the 5-meme minimum; the real UI only ever reaches this call from the
    reveal's final share step, which is itself gated on has_enough."""
    anon_user_id = get_anon_user_id(request)
    stats = await _stats_for(request, tz)
    if not stats.has_enough:
        raise HTTPException(status_code=400, detail="Not enough data yet for an Arc card")

    saved = await compose_arc_card(stats)
    await db.insert_meme(
        meme_id=saved.meme_id,
        url=saved.url,
        template_id=None,
        mode="arc",
        anon_user_id=anon_user_id,
        surface=None,
    )
    return ArcCardResponse(meme_id=saved.meme_id, url=saved.url)
