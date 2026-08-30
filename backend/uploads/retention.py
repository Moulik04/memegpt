"""
TTL-tracked temp-file cleanup — forward-looking infrastructure.

Phase 0/1 never write uploaded originals to disk (safe_ingest.py processes
everything in memory), so nothing here is exercised by today's code paths.
This exists for Phase 3 (video), which fundamentally needs a real file on
disk for ffmpeg to operate on, and any other future path that must touch
disk. The invariant: anything registered here is guaranteed deleted within
`upload_retention_seconds` (default 1 hour) even if the code that created
it crashes before cleaning up after itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterator
from pathlib import Path

from config import get_settings

logger = logging.getLogger(__name__)

_registry: dict[Path, float] = {}


@contextlib.contextmanager
def tracked_temp_file(path: Path) -> Iterator[Path]:
    """Register `path` for guaranteed deletion on both success and exception."""
    _registry[path] = time.time()
    try:
        yield path
    finally:
        _registry.pop(path, None)
        path.unlink(missing_ok=True)


def purge_expired(max_age_seconds: int | None = None) -> int:
    """Delete any tracked file older than max_age_seconds. Returns the count purged."""
    settings = get_settings()
    max_age = max_age_seconds if max_age_seconds is not None else settings.upload_retention_seconds
    now = time.time()
    expired = [p for p, created in _registry.items() if now - created > max_age]
    for p in expired:
        _registry.pop(p, None)
        p.unlink(missing_ok=True)
    if expired:
        logger.warning("purged_expired_uploads", extra={"count": len(expired)})
    return len(expired)


async def periodic_purge_loop(interval_seconds: int = 300) -> None:
    """Background sweep — started via asyncio.create_task() in main.py's
    lifespan, mirroring the existing _sequential_seed() pattern."""
    while True:
        await asyncio.sleep(interval_seconds)
        purge_expired()
