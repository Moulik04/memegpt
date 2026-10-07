"""
routers/share_intake.py — the short-lived handoff for photos and text sent
through the phone's share sheet. Covers the timed sweep: a share nobody
comes back for has to be dropped on a timer, not only when the next share
by someone else happens to trigger a purge.
"""

from __future__ import annotations

import asyncio

from routers import share_intake


async def test_an_abandoned_share_is_dropped_by_the_sweep_without_any_new_share():
    """Nobody picks this share up and nobody shares anything afterwards.
    The background sweep alone has to remove it."""
    share_intake._store.clear()
    share_intake._store["abandoned"] = {
        "images": [{"filename": "p.jpg", "content_type": "image/jpeg", "data": b"photo bytes"}],
        "text": None,
        "title": None,
        "created_at": share_intake.time.time() - share_intake._INTAKE_TTL_SECONDS - 1,
    }
    share_intake._store["fresh"] = {"images": [], "text": "hi", "title": None, "created_at": share_intake.time.time()}

    sweep = asyncio.create_task(share_intake.periodic_purge_loop(interval_seconds=0.01))
    await asyncio.sleep(0.05)
    sweep.cancel()

    assert "abandoned" not in share_intake._store
    assert "fresh" in share_intake._store
    share_intake._store.clear()
