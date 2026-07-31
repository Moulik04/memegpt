"""
DELETE /me/ — Growth Phase C "Forget me". Erases every row (memes,
feedback, lore_lexicon) tied to the caller's X-MemeGPT-User anon id.

200 no-op (not 404) when no header is sent — there's no "resource" to fail
to find here, and every other db.py function already treats absence as a
graceful no-op rather than an error. No listing endpoint exists anywhere in
this app, ever — this only ever acts on the id the caller presents.
"""

from fastapi import APIRouter, Request

import db
from identity import get_anon_user_id
from rate_limit import limiter
from schemas import ForgetMeResponse

router = APIRouter()


@router.delete("", response_model=ForgetMeResponse)  # "" not "/" — see api.ts's forgetMe() for why
@limiter.limit("5/minute")
async def forget_me(request: Request) -> ForgetMeResponse:
    anon_user_id = get_anon_user_id(request)
    if anon_user_id is not None:
        await db.delete_anon_user_data(anon_user_id)
    return ForgetMeResponse(status="ok")
