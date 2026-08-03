"""
Supabase Auth verification (Growth Phase H) — reads the caller's
`Authorization: Bearer <token>` header and, when Supabase Auth is
configured, verifies it against Supabase's own Auth server.

Deliberately NOT local JWT/JWKS decoding: Supabase's JWKS endpoint only
serves keys for projects using newer asymmetric signing keys (RS256/ES256)
— a project still on the legacy shared HS256 secret returns nothing there,
and this project's actual signing configuration was never checked. Calling
`GET /auth/v1/user` instead works regardless of that configuration, needs
zero secret management in this backend, and matches this repo's established
"raw httpx, no SDK" style already used for Groq/Anthropic/Gemini (see
nlp/vision.py's per-call `async with httpx.AsyncClient(...)` shape, mirrored
here).

Every caller treats an unverified/absent/misconfigured token as "no signed-
in user" — never an error. Same graceful-absence contract as identity.py's
get_anon_user_id(), which this sits alongside (not on top of): a request can
carry an anon id, a verified user, both, or neither.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import Request

from config import get_settings

_SUPABASE_USER_URL_SUFFIX = "/auth/v1/user"
_VERIFY_TIMEOUT_SECONDS = 10.0


@dataclass
class VerifiedUser:
    user_id: str
    email: str | None


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header[len("bearer "):].strip()
    return token or None


async def get_verified_user(request: Request) -> VerifiedUser | None:
    """None (never raises) when: Supabase isn't configured, no/malformed
    Authorization header is present, or Supabase rejects the token (expired,
    garbage, wrong project) — a failed/absent verification is always "no
    signed-in user", identical in spirit to identity.py's contract."""
    settings = get_settings()
    if not settings.supabase_url:
        return None

    token = _extract_bearer_token(request)
    if token is None:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    if settings.supabase_anon_key:
        headers["apikey"] = settings.supabase_anon_key

    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.supabase_url.rstrip('/')}{_SUPABASE_USER_URL_SUFFIX}",
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    user_id = data.get("id")
    if not user_id:
        return None
    return VerifiedUser(user_id=user_id, email=data.get("email"))
