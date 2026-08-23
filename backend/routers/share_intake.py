"""
POST /share-intake/       — stashes a shared payload (from the OS share sheet,
                            relayed by frontend/src/app/share/route.ts), returns a token.
GET  /share-intake/{token}/ — retrieves and evicts it (single-use).

This is a short-lived handoff, not an upload path: the Lore composer's
/chat/image/ submission is what actually runs uploads/safe_ingest.py and
moderation, exactly as it does for any normal attach-button upload. Stashed
images are NOT sanitized or moderated here — a user can still remove a
shared image in the composer before ever paying that cost, and duplicating
the safety pipeline at both stash and submission time would be wasted work
for content that might never actually be submitted.

In-memory dict, same "no locks needed — FastAPI async runs single-threaded
on the event loop" precedent as memory/conversation_store.py. This only
works because the backend runs as one Render web-service instance, not
horizontally-scaled serverless — unlike the Vercel-hosted frontend, which
is exactly why this stash lives here and not in the Next.js route handler.
"""

from __future__ import annotations

import base64
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from config import get_settings
from rate_limit import limiter

router = APIRouter()

_INTAKE_TTL_SECONDS = 600  # generous enough to cover opening the installed PWA after sharing
_store: dict[str, dict] = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v["created_at"] > _INTAKE_TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)


@router.post("/")
@limiter.limit(get_settings().upload_rate_limit)
async def stash_share(
    request: Request,
    images: list[UploadFile] = File(default=[]),
    text: str | None = Form(None),
    title: str | None = Form(None),
):
    """Basic sanity limits only (count/size) — real validation happens at
    actual /chat/image/ submission time via safe_ingest(). This just
    prevents a share sheet from trivially filling up server memory."""
    _purge_expired()
    settings = get_settings()

    if len(images) > settings.max_images_per_request:
        raise HTTPException(status_code=400, detail="Too many images shared at once")

    stored_images = []
    for img in images:
        data = await img.read()
        if len(data) > settings.max_image_bytes:
            raise HTTPException(status_code=400, detail="Shared image too large")
        stored_images.append({
            "filename": img.filename or "shared.jpg",
            "content_type": img.content_type or "image/jpeg",
            "data": data,
        })

    token = uuid.uuid4().hex
    _store[token] = {
        "images": stored_images,
        "text": text,
        "title": title,
        "created_at": time.time(),
    }
    return {"token": token}


@router.get("/{token}/")
async def retrieve_share(token: str):
    _purge_expired()
    entry = _store.pop(token, None)  # single-use — evict on read
    if entry is None:
        raise HTTPException(status_code=404, detail="This shared content is no longer available")

    return {
        "text": entry["text"],
        "title": entry["title"],
        "images": [
            {
                "filename": img["filename"],
                "content_type": img["content_type"],
                "data_base64": base64.b64encode(img["data"]).decode(),
            }
            for img in entry["images"]
        ],
    }
