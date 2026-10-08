"""
Shared slowapi Limiter instance.

Lives in its own module (rather than main.py) so router modules can import
it for their @limiter.limit(...) decorators without a circular import
(main.py imports the routers, so the routers can't import the limiter back
from main.py).
"""

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from notices import BUSY_MESSAGE, REASON_BUSY
from visitor import rate_limit_key

# Keyed on the visitor's address when the frontend's server vouches for it,
# and on the connection otherwise (visitor.py). The connection alone is the
# frontend's server for every Chat, Lore and Make request.
limiter = Limiter(key_func=rate_limit_key)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """slowapi's own handler, with the wording a visitor should see. Every
    limit here is per minute, so "try again in a minute" is true. `error`
    keeps slowapi's original text for anything that was reading it."""
    response = JSONResponse(
        {"detail": BUSY_MESSAGE, "reason": REASON_BUSY, "error": f"Rate limit exceeded: {exc.detail}"},
        status_code=429,
    )
    return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)
