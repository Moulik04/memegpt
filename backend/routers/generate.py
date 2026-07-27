from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

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
        saved = await compose_meme(
            template_id=request.template_id,
            texts=request.texts,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return MemeGenerationResponse(
        meme_url=saved.url,
        template_id=request.template_id,
        texts=request.texts,
    )


@router.get("/file/{template_id}")
async def generate_file(
    template_id: str,
    top: str = "",
    bottom: str = "",
):
    """Convenience GET — renders with top/bottom text and returns the raw
    image. Serves the file directly when storage is local-disk (true in
    every test environment and any deployment without R2 creds); redirects
    to the public URL when storage is R2 (saved.path is None — nothing
    local to serve)."""
    try:
        saved = await compose_meme(
            template_id=template_id,
            texts={"top_text": top, "bottom_text": bottom},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if saved.path is not None:
        return FileResponse(str(saved.path), media_type="image/png")
    return RedirectResponse(saved.url)
