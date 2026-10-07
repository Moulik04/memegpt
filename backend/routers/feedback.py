from fastapi import APIRouter, Request

import db
from auth import get_verified_user
from identity import get_anon_user_id
from rate_limit import limiter
from schemas import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
@limiter.limit("20/minute")
async def submit_feedback(request: Request, body: FeedbackRequest) -> FeedbackResponse:
    """
    Record user feedback on a generated meme.

    Every rating (👍 or 👎) is now recorded in Postgres — Growth Phase B
    fix for 👎 previously being silently discarded entirely. No-ops
    gracefully when DATABASE_URL isn't configured, same as every other
    Postgres write in this app.

    A rating is all this stores. It used to also turn a 👍 that arrived
    with a message and captions into a few-shot example, and those examples
    are quoted in the prompt for every later request on a similar topic.
    This route takes no sign-in, so that was a way for anyone to put text
    of their choosing into other people's prompts, kept in Postgres across
    restarts. The app itself never sent captions, so it never wrote one.
    `user_message` and `texts` are still accepted, for older clients, and
    ignored. Examples now come only from the curated seed set and the
    offline scripts (vector_db/examples_store.py).

    Growth Phase C: also persists anon_user_id and template_id on the
    feedback row itself (template_id was previously read off the request
    and silently dropped) — this is what lets the humor-profile aggregation
    in db.fetch_humor_profile() work without a lossy join through the
    nullable memes.meme_id relationship.

    Growth Phase H, Stage 2: also stamps a verified user_id alongside
    anon_user_id (never in place of it) when the request carries a valid
    Supabase bearer token — same "stamp both, key exclusively off user_id
    once present" pattern as every other Stage 2 write.
    """
    anon_user_id = get_anon_user_id(request)
    verified = await get_verified_user(request)
    await db.insert_feedback(
        meme_id=body.meme_id,
        rating=body.rating,
        conversation_id=body.conversation_id,
        anon_user_id=anon_user_id,
        template_id=body.template_id,
        user_id=verified.user_id if verified else None,
    )

    return FeedbackResponse(status="ok", rating=body.rating)
