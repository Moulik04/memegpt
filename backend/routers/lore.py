"""
POST /lore/       — Lore surface (text), returns Server-Sent Events.
POST /lore/image/ — Lore surface multimodal (1+ photos), same SSE contract.

Growth Phase D split: Lore is now a genuinely separate endpoint from Chat,
with its own request model (LoreRequest, exposing meme_count + remember_lore
that Chat deliberately doesn't). It shares the entire streaming core with
Chat via routers/chat.py's handle_text_stream / handle_image_stream — the
only differences are these extra controls and the surface="lore" stamp that
gets written onto every generated meme (powering Arc's Chat-vs-Lore split).

routers/chat.py never imports this module, so importing its helpers here is
cycle-free.
"""

from fastapi import APIRouter, File, Form, Request, UploadFile

from config import get_settings
from rate_limit import limiter
from routers.chat import handle_image_stream, handle_text_stream
from schemas import LoreRequest

router = APIRouter()


@router.post("/")
async def lore(request: Request, body: LoreRequest):
    """Lore surface — big-context dumps, explicit meme-count override, opt-in
    Lore lexicon. Delegates to Chat's shared core with surface="lore"."""
    return await handle_text_stream(
        request, body.message, body.conversation_id,
        meme_count=body.meme_count, remember_lore=body.remember_lore, surface="lore",
        conversation_row_id_in=body.conversation_row_id,
    )


@router.post("/image/")
@limiter.limit(get_settings().upload_rate_limit)
async def lore_with_image(
    request: Request,  # required by slowapi's key_func, unused otherwise
    images: list[UploadFile] = File(...),
    message: str | None = Form(None),
    conversation_id: str | None = Form(None),
    meme_count: int | None = Form(None),
    mode: str | None = Form(None),
    remember_lore: bool = Form(False),
    conversation_row_id: str | None = Form(None),
):
    """Lore surface multimodal — same as /chat/image/ plus meme_count and
    remember_lore, stamped surface="lore"."""
    return await handle_image_stream(
        request, images, message, conversation_id,
        meme_count=meme_count, mode=mode, remember_lore=remember_lore, surface="lore",
        conversation_row_id_in=conversation_row_id,
    )
