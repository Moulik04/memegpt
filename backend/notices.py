"""
The three "MemeGPT can't make that meme right now" cases, and the one
message each of them gets. They used to be worded where they were raised,
which is how "try again in a minute" ended up on a limit that takes hours
to clear.

A notice travels as an SSE `error` event (or, from Make, as the JSON body of
an error response) with a `reason` next to the `message`. An old frontend
shows the message. A current one also reads the reason: for REASON_SITE_BUDGET
it shows one of its pre-made budget memes beside the text. Those images are
static files on the frontend. Nothing here renders, stores or counts them.
"""

from __future__ import annotations

# The model provider's per-minute limit, or this app's own per-minute
# request limit. A minute really is enough.
REASON_BUSY = "busy"
BUSY_MESSAGE = "MemeGPT is busy, try again in a minute."

# The model provider's daily limit, shared by every visitor. Owner's wording.
REASON_SITE_BUDGET = "site_budget"
DAILY_BUDGET_MESSAGE = (
    "MemeGPT runs on a free daily AI budget, and today's is used up. "
    "It refills gradually, so try again in a few hours."
)

# This visitor's own allowance (daily_quota.py). Owner's wording for the
# per-browser case. The per-network one says whose allowance it was: someone
# opening the app for the first time on a busy network has made no memes.
REASON_VISITOR_LIMIT = "visitor_limit"


def visitor_limit_message(limit: int, *, network: bool = False) -> str:
    if network:
        return f"Your network has made its {limit} memes for today. They refill over the next 24 hours."
    return f"That's your {limit} memes for today. They refill over the next 24 hours."


def notice_event(reason: str, message: str, **extra) -> dict:
    return {"type": "error", "message": message, "reason": reason, **extra}
