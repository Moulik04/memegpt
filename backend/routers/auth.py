"""
GET /auth/whoami — Growth Phase H, Stage 1. The one testable checkpoint for
this stage: verifies the caller's Supabase bearer token (if any) and reports
back the identity, without any other endpoint reading it yet.
"""

from fastapi import APIRouter, Request

from auth import get_verified_user
from schemas import WhoAmIResponse

router = APIRouter()


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(request: Request) -> WhoAmIResponse:
    user = await get_verified_user(request)
    if user is None:
        return WhoAmIResponse()
    return WhoAmIResponse(user_id=user.user_id, email=user.email)
