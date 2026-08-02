"""
vector_db/chroma_client.py's upsert_templates_batch_with_embeddings() —
the precomputed-vector path added to stop every backend restart from
re-embedding the whole template catalog live against Gemini (Render's
disk is ephemeral, so this was happening on every single restart before
scripts/precompute_template_embeddings.py existed). Covers: embeddings=
actually reaches ChromaDB's upsert() call, and the document/metadata
shape stays identical to the existing live-embedding path
(upsert_templates_batch) — same shared template_document_text() helper.
"""

from __future__ import annotations

import vector_db.chroma_client as chroma_client


class _FakeCollection:
    def __init__(self):
        self.calls = []

    def upsert(self, **kwargs):
        self.calls.append(kwargs)


def test_upsert_templates_batch_with_embeddings_passes_embeddings_through(monkeypatch):
    fake_col = _FakeCollection()
    monkeypatch.setattr(chroma_client, "_get_collection", lambda: fake_col)

    records = [
        {
            "template_id": "drake",
            "name": "Drake",
            "tags": ["drake"],
            "description": "A settled preference.",
            "embedding": [0.1, 0.2, 0.3],
        },
        {
            "template_id": "grus_plan",
            "name": "Grus Plan",
            "tags": ["grus_plan"],
            "description": "A plan that backfires.",
            "embedding": [0.4, 0.5, 0.6],
        },
    ]

    chroma_client.upsert_templates_batch_with_embeddings(records)

    assert len(fake_col.calls) == 1
    call = fake_col.calls[0]
    assert call["ids"] == ["drake", "grus_plan"]
    assert call["embeddings"] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert call["documents"] == [
        chroma_client.template_document_text("Drake", "A settled preference.", ["drake"]),
        chroma_client.template_document_text("Grus Plan", "A plan that backfires.", ["grus_plan"]),
    ]
    assert call["metadatas"][0]["name"] == "Drake"


def test_upsert_templates_batch_with_embeddings_noop_on_empty(monkeypatch):
    fake_col = _FakeCollection()
    monkeypatch.setattr(chroma_client, "_get_collection", lambda: fake_col)

    chroma_client.upsert_templates_batch_with_embeddings([])

    assert fake_col.calls == []


def test_template_document_text_matches_between_live_and_precomputed_paths():
    """The exact bug class this shared helper prevents: a precompute
    script independently reconstructing the document string slightly
    differently than the live path, silently producing a "precomputed"
    embedding that doesn't actually correspond to what live embedding
    would have computed for the same template."""
    text = chroma_client.template_document_text("Drake", "desc here", ["drake", "meme"])
    assert text == "Drake. desc here. Tags: drake, meme."
