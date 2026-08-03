"""
GET /auth/whoami    — Growth Phase H, Stage 1. Verifies the caller's
                       Supabase bearer token (if any) and reports back the
                       identity.
POST /auth/link-anon — Growth Phase H, Stage 2. Links the caller's existing
                       anonymous history (X-MemeGPT-User) to their verified
                       account, one time, idempotently.
"""

from fastapi import APIRouter, Request

import db
from auth import get_verified_user
from identity import get_anon_user_id
from schemas import LinkAnonResponse, WhoAmIResponse

router = APIRouter()


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(request: Request) -> WhoAmIResponse:
    user = await get_verified_user(request)
    if user is None:
        return WhoAmIResponse()
    return WhoAmIResponse(user_id=user.user_id, email=user.email)


@router.post("/link-anon", response_model=LinkAnonResponse)
async def link_anon(request: Request) -> LinkAnonResponse:
    """Called once by the frontend on Supabase's SIGNED_IN event — never a
    hard requirement (a signed-in user with no anon header, or one whose
    token doesn't verify, just gets migrated=False, not an error). Safe to
    call repeatedly: migrate_anon_data_to_user()'s WHERE user_id IS NULL
    guard makes every statement idempotent."""
    anon_user_id = get_anon_user_id(request)
    user = await get_verified_user(request)
    if anon_user_id is None or user is None:
        return LinkAnonResponse(status="ok", migrated=False)
    rows_linked = await db.migrate_anon_data_to_user(anon_user_id, user.user_id)
    return LinkAnonResponse(status="ok", migrated=rows_linked > 0)
