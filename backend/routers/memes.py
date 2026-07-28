"""
GET /memes/{id} — Growth Phase B share pages. Reads from the durable
memes Postgres table (db.fetch_meme) and returns url + template display
name ONLY — never situation text, dump text, or captions, matching the
memes table's own privacy rule. 404s when Postgres is unset or the id
doesn't exist; there's nothing durable to serve either way. No listing
endpoint exists anywhere in this app — this is a single lookup by a
specific, unguessable id, the only way in.
"""

from fastapi import APIRouter, HTTPException, Request

import db
from rate_limit import limiter
from schemas import SharedMemeResponse
from vector_db.chroma_client import get_template_record

router = APIRouter()


def _template_display_name(template_id: str | None) -> str | None:
    """Canvas-mode memes have no template_id — None is the correct answer
    for those, not an error."""
    if template_id is None:
        return None
    record = get_template_record(template_id)
    if record and record.get("name"):
        return record["name"]
    return template_id.replace("_", " ").title()


@router.get("/{meme_id}", response_model=SharedMemeResponse)
@limiter.limit("30/minute")
async def get_meme(request: Request, meme_id: str) -> SharedMemeResponse:
    meme = await db.fetch_meme(meme_id)
    if meme is None:
        raise HTTPException(status_code=404, detail="Meme not found")
    return SharedMemeResponse(
        url=meme["url"],
        template_name=_template_display_name(meme["template_id"]),
    )
