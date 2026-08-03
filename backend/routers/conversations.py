"""
Growth Phase H, Stage 3 — persisted chat history (signed-in only).

Every route requires a verified Supabase user (get_verified_user) — there
is no anonymous equivalent, matching the master prompt spec's "signed-in
only" scope for this feature. GET routes degrade to an empty/404 response
when unauthenticated (never an error); the two writes (POST, and implicitly
PATCH/DELETE) 401 outright, since there's no sensible no-op for "create a
conversation for nobody."

No listing-by-someone-else's-id endpoint exists — every ownership-sensitive
db.py call pairs the client-supplied id with the verified user_id, same
"never trust a bare id" posture as every other Stage 3 primitive.
"""

from fastapi import APIRouter, HTTPException, Request

import db
from auth import get_verified_user
from rate_limit import limiter
from schemas import (
    ConversationCreatedResponse,
    ConversationSummary,
    CreateConversationRequest,
    MessageOut,
    RenameConversationRequest,
)

router = APIRouter()


async def _require_user_id(request: Request) -> str:
    user = await get_verified_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign-in required")
    return user.user_id


@router.get("", response_model=list[ConversationSummary])
@limiter.limit("30/minute")
async def list_conversations(request: Request, surface: str | None = None) -> list[ConversationSummary]:
    user = await get_verified_user(request)
    if user is None:
        return []
    rows = await db.fetch_conversations(user.user_id, surface=surface)
    return [ConversationSummary(**row) for row in rows]


@router.post("", response_model=ConversationCreatedResponse)
@limiter.limit("10/minute")
async def create_conversation(request: Request, body: CreateConversationRequest) -> ConversationCreatedResponse:
    user_id = await _require_user_id(request)
    conversation_id = await db.create_conversation(user_id, body.surface)
    if conversation_id is None:
        raise HTTPException(status_code=503, detail="Chat history isn't available right now")
    return ConversationCreatedResponse(id=conversation_id, surface=body.surface)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
@limiter.limit("30/minute")
async def get_conversation_messages(request: Request, conversation_id: str) -> list[MessageOut]:
    user = await get_verified_user(request)
    if user is None:
        raise HTTPException(status_code=404, detail="Not found")
    messages = await db.fetch_messages(conversation_id, user.user_id)
    if messages is None:
        # Not-found and not-owned are deliberately indistinguishable —
        # never leak which one it was to the caller.
        raise HTTPException(status_code=404, detail="Not found")
    return [MessageOut(**m) for m in messages]


@router.patch("/{conversation_id}", response_model=ConversationSummary)
@limiter.limit("10/minute")
async def rename_conversation(
    request: Request, conversation_id: str, body: RenameConversationRequest
) -> ConversationSummary:
    user_id = await _require_user_id(request)
    renamed = await db.rename_conversation(conversation_id, user_id, body.title)
    if not renamed:
        raise HTTPException(status_code=404, detail="Not found")
    updated = await db.fetch_conversation(conversation_id, user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Not found")
    return ConversationSummary(**updated)


@router.delete("/{conversation_id}")
@limiter.limit("10/minute")
async def delete_conversation(request: Request, conversation_id: str) -> dict:
    user_id = await _require_user_id(request)
    deleted = await db.delete_conversation(conversation_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok"}
