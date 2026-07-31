"""
Anonymous identity (Growth Phase C) — reads the frontend's self-generated,
no-signup `X-MemeGPT-User` header. Lives in its own module, same reasoning
as rate_limit.py: routers need it and main.py wires routers, so a router
module can't import this back from main.py without a cycle.

Every caller treats a missing/absent header as "no personalization for this
request" — never an error. That's what keeps Phase C's degrade-cleanly
requirement true by construction: an anon id is a nice-to-have hint, never
a dependency.
"""

from __future__ import annotations

from fastapi import Request

_HEADER_NAME = "X-MemeGPT-User"
_MAX_LEN = 128  # defensive cap on a client-supplied string headed into DB writes


def get_anon_user_id(request: Request) -> str | None:
    """Opaque string, not validated as a UUID — no reason to couple the
    backend to the frontend's exact id scheme."""
    value = request.headers.get(_HEADER_NAME)
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:_MAX_LEN]
