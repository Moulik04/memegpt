from fastapi import APIRouter, HTTPException

from image_processing.compositor import template_image_url
from image_processing.template_configs import get_config
from schemas import ExplainRequest, ExplainResponse, TextBoxInfo
from vector_db.chroma_client import get_template_record, list_all_template_records

router = APIRouter()


def _text_boxes_for(template_id: str) -> list[TextBoxInfo]:
    config = get_config(template_id)
    return [
        TextBoxInfo(
            label=box.label,
            description=config.box_descriptions.get(box.label, ""),
        )
        for box in config.text_boxes
    ]


def _build_response(record: dict, template_id: str) -> ExplainResponse:
    return ExplainResponse(
        template_id=template_id,
        name=record.get("name", "Unknown"),
        description=record.get("description", ""),
        tags=record.get("tags", []),
        usage_count=record.get("usage_count", 0),
        recent_uses=record.get("recent_uses", []),
        image_url=template_image_url(template_id),
        text_boxes=_text_boxes_for(template_id),
    )


@router.get("/", response_model=list[ExplainResponse])
async def list_templates() -> list[ExplainResponse]:
    """
    Every template's metadata in one call — powers the manual meme-maker's
    template picker (Phase 4, paired with POST /generate/).
    """
    return [
        _build_response(record, record["template_id"])
        for record in list_all_template_records()
    ]


@router.post("/", response_model=ExplainResponse)
async def explain(request: ExplainRequest) -> ExplainResponse:
    """
    Returns metadata, usage history, and caption-field structure for a
    given meme template.

    Useful for the frontend's "Why this meme?" tooltip / info drawer, and
    for the manual meme-maker once a template is picked from the grid.
    """
    record = get_template_record(request.template_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{request.template_id}' not found in vector store.",
        )

    return _build_response(record, request.template_id)
