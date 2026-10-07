"""
The template usage log (vector_db/chroma_client.log_usage) and the public
template endpoints that read it. A count per template is all that may be
kept or returned: it once kept the last 20 captions per template with the
conversation they came from, and GET /explain/ returned them to anyone.
"""

from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient

from main import app
from vector_db import chroma_client

_TEMPLATE = "usage_log_test_template"
_OLD_ENTRIES = json.dumps([
    {"ts": "2026-01-01T00:00:00+00:00", "top_text": "SECRET CAPTION FROM A PASTE",
     "bottom_text": "ANOTHER LINE", "conversation_id": "conv-123"},
])


def _seed(recent_uses: str = "[]") -> None:
    chroma_client.upsert_template(
        template_id=_TEMPLATE, name="Usage Log Test", description="a template for this test", tags=["test"],
    )
    col = chroma_client._get_collection()
    meta = col.get(ids=[_TEMPLATE])["metadatas"][0]
    col.update(ids=[_TEMPLATE], metadatas=[{**meta, "usage_count": 0, "recent_uses": recent_uses}])


def _stored() -> dict:
    return chroma_client._get_collection().get(ids=[_TEMPLATE])["metadatas"][0]


def test_log_usage_counts_and_keeps_nothing_else():
    _seed()

    chroma_client.log_usage(_TEMPLATE)
    chroma_client.log_usage(_TEMPLATE)

    stored = _stored()
    assert stored["usage_count"] == 2
    assert json.loads(stored["recent_uses"]) == []


def test_log_usage_blanks_what_an_older_version_stored():
    _seed(_OLD_ENTRIES)

    chroma_client.log_usage(_TEMPLATE)

    assert "SECRET CAPTION" not in json.dumps(_stored())


def test_purge_clears_stored_captions_without_touching_the_count():
    _seed(_OLD_ENTRIES)
    chroma_client._get_collection().update(ids=[_TEMPLATE], metadatas=[{**_stored(), "usage_count": 7}])

    cleaned = chroma_client.purge_logged_captions()

    assert cleaned >= 1
    stored = _stored()
    assert "SECRET CAPTION" not in json.dumps(stored)
    assert "conv-123" not in json.dumps(stored)
    assert stored["usage_count"] == 7
    assert chroma_client.purge_logged_captions() == 0  # nothing left to clean


async def test_public_template_endpoints_return_no_usage_history():
    """Even with old entries still sitting in storage, neither endpoint may
    hand them out."""
    _seed(_OLD_ENTRIES)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/explain/")
        single = await client.post("/explain/", json={"template_id": _TEMPLATE})

    assert listing.status_code == 200 and single.status_code == 200
    for body in (listing.text, single.text):
        assert "SECRET CAPTION" not in body
        assert "conv-123" not in body
        assert "recent_uses" not in body
    assert single.json()["usage_count"] == 0
