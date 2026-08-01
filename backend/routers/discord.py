"""
POST /discord/generate — Growth Phase G, the backend half of the /meme
Discord slash command.

**Discord itself never talks to this endpoint.** Discord's Interactions
API requires ed25519 signature verification on every request (including
its PING handshake) AND a response within 3 seconds — Render's free tier
can cold-start in ~30s, so it structurally cannot be the thing Discord's
"Interactions Endpoint URL" points at. That's the Cloudflare Worker
(integrations/discord-worker/): it's what Discord actually sends the PING
and every real interaction to, it verifies the signature itself (the real
security boundary for this whole feature), acks within 3s with a deferred
response, then calls THIS endpoint from its own backend, and finally
PATCHes Discord's follow-up webhook once it has a result.

Because Discord never reaches this endpoint directly, this backend never
needs DISCORD_PUBLIC_KEY or DISCORD_APP_ID for anything — its only
authentication is a pre-shared secret between the Worker and this backend
(X-Discord-Worker-Secret), which exists purely to stop a random public
caller from hitting a real-compute-costing endpoint, not to satisfy
Discord's own protocol.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request

from config import get_settings
from rate_limit import limiter
from routers.chat import generate_single_meme
from schemas import DiscordGenerateRequest, DiscordGenerateResponse

router = APIRouter()


def _check_shared_secret(request: Request) -> None:
    settings = get_settings()
    if not settings.discord_worker_shared_secret:
        # Fails closed, same posture as uploads/moderation.py's "can't
        # verify = treat as rejected" — an unconfigured secret must never
        # silently pass every request through.
        raise HTTPException(status_code=503, detail="Discord integration not configured")
    provided = request.headers.get("x-discord-worker-secret", "")
    if provided != settings.discord_worker_shared_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing shared secret")


@router.post("/generate", response_model=DiscordGenerateResponse)
@limiter.limit(get_settings().discord_rate_limit)
async def generate(request: Request, body: DiscordGenerateRequest) -> DiscordGenerateResponse:
    _check_shared_secret(request)

    try:
        response = await generate_single_meme(
            user_message=body.text,
            conversation_id=str(uuid.uuid4()),
            surface="discord",
        )
    except Exception as exc:
        # Deliberately generic — the Worker turns this into a short
        # friendly follow-up message, not a leaked internal error string.
        raise HTTPException(status_code=500, detail="Meme generation failed") from exc

    return DiscordGenerateResponse(
        meme_url=response.message.meme_url,
        template_id=response.template_used,
    )
