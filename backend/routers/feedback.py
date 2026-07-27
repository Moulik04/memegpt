from fastapi import APIRouter

import db
from schemas import FeedbackRequest, FeedbackResponse
from vector_db.examples_store import upsert_example

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
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
    """
    await db.insert_feedback(
        meme_id=request.meme_id,
        rating=request.rating,
        conversation_id=request.conversation_id,
    )

    if request.rating == "up" and request.user_message and request.texts:
        await upsert_example(
            user_message=request.user_message,
            template_id=request.template_id,
            texts=request.texts,
        )

    return FeedbackResponse(status="ok", rating=request.rating)
