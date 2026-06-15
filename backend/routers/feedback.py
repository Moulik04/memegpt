from fastapi import APIRouter

from schemas import FeedbackRequest, FeedbackResponse
from vector_db.examples_store import upsert_example

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Record user feedback on a generated meme.

    👍 (up)   → stores the (user_message, template_id, texts) triplet as a
               positive few-shot example in ChromaDB so future similar queries
               are more likely to pick the same template.

    👎 (down) → logged but not stored (future: negative-example retrieval).
    """
    if request.rating == "up" and request.user_message and request.texts:
        upsert_example(
            user_message=request.user_message,
            template_id=request.template_id,
            texts=request.texts,
        )

    return FeedbackResponse(status="ok", rating=request.rating)
