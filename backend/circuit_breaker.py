"""
A tiny in-process circuit breaker — module-level state, no locks needed
(same "single persistent event loop" precedent already used by
memory/conversation_store.py and share_intake.py's stash).

Used to stop paying a retry/latency tax on a request we already know is
going to fail (Groq or Gemini rate-limited within the last N seconds),
instead of finding that out again on every single subsequent request
during an outage window. The underlying call site's own graceful-degrade
path (Gemini: empty RAG results; Groq: try a different model, or the
hardcoded fallback meme) is unchanged — this only decides whether to
bother attempting the call at all.
"""

from __future__ import annotations

import time

_open_until: dict[str, float] = {}


def is_open(name: str) -> bool:
    """True if `name`'s circuit is currently tripped (still within its
    cooldown window) — the caller should skip attempting the call."""
    return time.monotonic() < _open_until.get(name, 0.0)


def trip(name: str, cooldown_seconds: float) -> None:
    """Record that `name` just failed in a way that's likely to keep
    failing for a while (e.g. a rate limit) — is_open(name) returns True
    until cooldown_seconds from now."""
    _open_until[name] = time.monotonic() + cooldown_seconds


def reset(name: str) -> None:
    """Record that `name` just succeeded — clears any open circuit early
    rather than waiting out the rest of a cooldown that's no longer
    accurate."""
    _open_until.pop(name, None)
