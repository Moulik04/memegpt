from fastapi import APIRouter, HTTPException

from schemas import ExplainRequest, ExplainResponse
from vector_db.chroma_client import get_template_record

router = APIRouter()


@router.post("/", response_model=ExplainResponse)
async def explain(request: ExplainRequest) -> ExplainResponse:
    """
    Returns metadata and usage history for a given meme template.

    Useful for the frontend's "Why this meme?" tooltip / info drawer.
    """
    record = get_template_record(request.template_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{request.template_id}' not found in vector store.",
        )

    return ExplainResponse(
        template_id=request.template_id,
        name=record.get("name", "Unknown"),
        description=record.get("description", ""),
        tags=record.get("tags", []),
        usage_count=record.get("usage_count", 0),
        recent_uses=record.get("recent_uses", []),
    )
