"""
DELETE /me — "Forget me". Erases what the caller owns: everything tied to
the account they are signed in to, plus everything tied to their browser's
anonymous id that belongs to no account (see db.delete_identity_data for the
exact rule and the full list). Stored meme images are removed along with
the rows that name them.

Two things this must never do:

  - Report success for an erase that did not happen. Every failure —
    storage, database, anything unexpected — is a 500 with a message the
    page shows, never a quiet 200. A request that carries a sign-in token
    which does not verify is refused (401) rather than treated as signed
    out: quietly erasing only the anonymous half would look like success to
    someone who asked for their account's history to go.
  - Leave an image behind that nothing points to any more. Images are
    removed first, while the rows still say where they are. If that step
    fails nothing else has been touched and the request can simply be
    retried; removing an image that is already gone is not an error.

200 no-op (not 404) when no identity is sent at all — there is nothing to
erase and nothing to fail to find. No listing endpoint exists anywhere in
this app, ever — this only ever acts on the identity the caller presents.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

import db
import storage
from auth import get_verified_user
from identity import get_anon_user_id
from rate_limit import limiter
from schemas import ForgetMeResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_SIGN_IN_NOT_CONFIRMED = (
    "MemeGPT couldn't confirm your sign-in, so nothing was erased. Sign in again and retry."
)
_ERASE_FAILED = "MemeGPT couldn't finish erasing your data. Please try again."


@router.delete("", response_model=ForgetMeResponse)  # "" not "/" — see api.ts's forgetMe() for why
@limiter.limit("5/minute")
async def forget_me(request: Request) -> ForgetMeResponse:
    anon_user_id = get_anon_user_id(request)
    verified = await get_verified_user(request)
    if verified is None and request.headers.get("Authorization"):
        raise HTTPException(status_code=401, detail=_SIGN_IN_NOT_CONFIRMED)
    user_id = verified.user_id if verified else None

    if anon_user_id is None and user_id is None:
        return ForgetMeResponse(status="ok")

    try:
        memes = await db.fetch_identity_memes(anon_user_id, user_id)
        await storage.delete_memes(memes)
        erased = await db.delete_identity_data(anon_user_id, user_id)
        # A meme generated between the read above and the transaction is in
        # `erased` but was not in `memes`. Rare, and its row is already gone,
        # so this is the last chance to remove its image.
        already_removed = set(memes)
        await storage.delete_memes([meme for meme in erased if meme not in already_removed])
    except Exception as exc:
        logger.exception("forget_me_failed")
        raise HTTPException(status_code=500, detail=_ERASE_FAILED) from exc

    return ForgetMeResponse(status="ok")
