from fastapi import APIRouter, Request

import db
from identity import get_anon_user_id
from schemas import FeedbackRequest, FeedbackResponse
from vector_db.examples_store import upsert_example

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(request: Request, body: FeedbackRequest) -> FeedbackResponse:
    """
    Record user feedback on a generated meme.

    Every rating (👍 or 👎) is now recorded in Postgres — Growth Phase B
    fix for 👎 previously being silently discarded entirely. No-ops
    gracefully when DATABASE_URL isn't configured, same as every other
    Postgres write in this app.

    👍 (up)   → additionally stores the (user_message, template_id, texts)
               triplet as a positive few-shot example in ChromaDB + Postgres
               so future similar queries are more likely to pick the same
               template.

    👎 (down) → recorded in the feedback table only; no few-shot example.

    Growth Phase C: also persists anon_user_id and template_id on the
    feedback row itself (template_id was previously read off the request
    and silently dropped) — this is what lets the humor-profile aggregation
    in db.fetch_humor_profile() work without a lossy join through the
    nullable memes.meme_id relationship.
    """
    anon_user_id = get_anon_user_id(request)
    await db.insert_feedback(
        meme_id=body.meme_id,
        rating=body.rating,
        conversation_id=body.conversation_id,
        anon_user_id=anon_user_id,
        template_id=body.template_id,
    )

    if body.rating == "up" and body.user_message and body.texts:
        await upsert_example(
            user_message=body.user_message,
            template_id=body.template_id,
            texts=body.texts,
        )

    return FeedbackResponse(status="ok", rating=body.rating)
