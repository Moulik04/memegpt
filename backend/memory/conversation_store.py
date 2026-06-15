"""
In-memory conversation state store.

Tracks which meme templates were used in each conversation so the LLM
can be instructed to avoid repeating them within the same session.

Uses a plain dict (no locks needed — FastAPI async runs single-threaded
on the event loop). Capped at 20 turns per conversation to prevent unbounded growth.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

_store: dict[str, list[dict]] = defaultdict(list)
_MAX_TURNS = 20


def add_turn(conversation_id: str, template_id: str) -> None:
    turns = _store[conversation_id]
    turns.append({
        "template_id": template_id,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    })
    if len(turns) > _MAX_TURNS:
        _store[conversation_id] = turns[-_MAX_TURNS:]


def get_recent_templates(conversation_id: str, n: int = 5) -> list[str]:
    """Return the last N template IDs used — passed to the LLM to prevent repetition."""
    turns = _store.get(conversation_id, [])
    return [t["template_id"] for t in turns[-n:]]


def clear(conversation_id: str) -> None:
    _store.pop(conversation_id, None)
