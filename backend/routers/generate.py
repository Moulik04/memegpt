from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

import db
from auth import get_verified_user
from identity import get_anon_user_id
from image_processing.compositor import compose_meme
from nlp.text_moderation import moderate_text
from rate_limit import limiter
from schemas import MemeGenerationRequest, MemeGenerationResponse

router = APIRouter()

_GENERIC_CAPTION_REFUSAL = "That caption couldn't be used — try different text."


@router.post("/", response_model=MemeGenerationResponse)
@limiter.limit("20/minute")
async def generate(request: Request, body: MemeGenerationRequest) -> MemeGenerationResponse:
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

    Stamps identity + surface="make" on the resulting meme the same way
    chat.py/lore.py do (was missing entirely before — Make usage was
    invisible to Arc's stats and to "Forget me", since nothing tied a
    Make-generated meme to any user at all).
    """
    combined_text = "\n".join(body.texts.values())
    moderation = await moderate_text(combined_text)
    if not moderation.passed:
        raise HTTPException(status_code=400, detail=_GENERIC_CAPTION_REFUSAL)

    try:
        saved = await compose_meme(
            template_id=body.template_id,
            texts=body.texts,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
