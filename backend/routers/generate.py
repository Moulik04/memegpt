from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from image_processing.compositor import compose_meme
from schemas import MemeGenerationRequest, MemeGenerationResponse

router = APIRouter()


@router.post("/", response_model=MemeGenerationResponse)
async def generate(request: MemeGenerationRequest) -> MemeGenerationResponse:
    """
    On-demand meme generation endpoint.

    Accepts a template_id and a dict of label→text pairs matching
    the template's TextBoxConfig labels (e.g. {"rejected_option": "...", "approved_option": "..."}).
    """
    try:
        meme_url = await compose_meme(
            template_id=request.template_id,
            texts=request.texts,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return MemeGenerationResponse(
        meme_url=meme_url,
        template_id=request.template_id,
        texts=request.texts,
    )


@router.get("/file/{template_id}")
async def generate_file(
    template_id: str,
    top: str = "",
    bottom: str = "",
) -> FileResponse:
    """Convenience GET — renders with top/bottom text and returns the raw image file."""
    try:
        meme_path = await compose_meme(
            template_id=template_id,
            texts={"top_text": top, "bottom_text": bottom},
            return_path=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(str(meme_path), media_type="image/png")
