"""
main.py's _auto_seed_if_empty(): Gemini rate-limiting during startup
seeding can exhaust the retry budget on one chunk, raising uncaught and
killing every remaining chunk. If the collection isn't empty anymore (an
earlier chunk already landed), an "only seed when fully empty" guard would
mean the catalog stays permanently partial — this function would never run
again. Covers the fix: not gated on emptiness, and one failing chunk
doesn't prevent the rest from being attempted.
"""

from __future__ import annotations

import json

import main


def _make_template_files(tmp_path, names: list[str]):
    for name in names:
        (tmp_path / f"{name}.jpg").write_bytes(b"fake")


def test_seeds_missing_templates_even_when_collection_is_not_empty(monkeypatch, tmp_path):
    _make_template_files(tmp_path, ["drake", "grus_plan", "new_template"])
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: ["drake", "grus_plan"])

    seeded_ids = []

    def fake_upsert_batch(records):
        seeded_ids.extend(r["template_id"] for r in records)

    monkeypatch.setattr(main, "upsert_templates_batch", fake_upsert_batch)

    main._auto_seed_if_empty()

    assert seeded_ids == ["new_template"]


def test_does_nothing_when_nothing_is_missing(monkeypatch, tmp_path):
    _make_template_files(tmp_path, ["drake"])
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: ["drake"])

    calls = []
    monkeypatch.setattr(main, "upsert_templates_batch", lambda records: calls.append(records))

    main._auto_seed_if_empty()

    assert calls == []


def test_one_failing_chunk_does_not_prevent_remaining_chunks(monkeypatch, tmp_path):
    names = [f"template_{i}" for i in range(45)]  # 3 chunks at _SEED_CHUNK_SIZE=20
    _make_template_files(tmp_path, names)
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: [])
    monkeypatch.setattr(main, "_SEED_CHUNK_SIZE", 20)

    attempted_chunks = []

    def flaky_upsert_batch(records):
        attempted_chunks.append(len(records))
        if len(attempted_chunks) == 2:  # the second chunk hits a simulated rate limit
            raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(main, "upsert_templates_batch", flaky_upsert_batch)

    main._auto_seed_if_empty()  # must not raise

    assert len(attempted_chunks) == 3  # all 3 chunks were attempted despite chunk 2 failing


def _stub_settings_gemini_key(monkeypatch, key: str):
    class _FakeSettings:
        gemini_api_key = key

    monkeypatch.setattr(main, "settings", _FakeSettings())


def test_uses_precomputed_embeddings_when_gemini_configured_and_document_matches(monkeypatch, tmp_path):
    # A template_id deliberately absent from the real USE_WHEN dict, so its
    # description deterministically falls back to "Meme template: <Name>"
    # regardless of the real catalog's content.
    _make_template_files(tmp_path, ["totally_fake_test_template"])
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: [])
    _stub_settings_gemini_key(monkeypatch, "fake-gemini-key")

    document = main.template_document_text(
        "Totally Fake Test Template", "Meme template: Totally Fake Test Template", ["totally_fake_test_template"]
    )
    embeddings_file = tmp_path / "template_embeddings.json"
    embeddings_file.write_text(json.dumps({
        "totally_fake_test_template": {"embedding": [0.1, 0.2], "document": document},
    }))
    monkeypatch.setattr(main, "_PRECOMPUTED_EMBEDDINGS_PATH", embeddings_file)

    live_calls = []
    fast_calls = []
    monkeypatch.setattr(main, "upsert_templates_batch", lambda records: live_calls.append(records))
    monkeypatch.setattr(main, "upsert_templates_batch_with_embeddings", lambda records: fast_calls.append(records))

    main._auto_seed_if_empty()

    assert live_calls == []  # never touched Gemini
    assert len(fast_calls) == 1
    assert fast_calls[0][0]["template_id"] == "totally_fake_test_template"
    assert fast_calls[0][0]["embedding"] == [0.1, 0.2]


def test_falls_back_to_live_embedding_when_precomputed_entry_is_stale(monkeypatch, tmp_path):
    """A stale precomputed entry (description changed since the last
    precompute run) must never be trusted — falls through to a real
    embed for that one template rather than silently using a mismatched
    vector."""
    _make_template_files(tmp_path, ["drake"])
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: [])
    _stub_settings_gemini_key(monkeypatch, "fake-gemini-key")

    embeddings_file = tmp_path / "template_embeddings.json"
    embeddings_file.write_text(json.dumps({
        "drake": {"embedding": [0.1, 0.2], "document": "some stale outdated description"},
    }))
    monkeypatch.setattr(main, "_PRECOMPUTED_EMBEDDINGS_PATH", embeddings_file)

    live_calls = []
    fast_calls = []
    monkeypatch.setattr(main, "upsert_templates_batch", lambda records: live_calls.append(records))
    monkeypatch.setattr(main, "upsert_templates_batch_with_embeddings", lambda records: fast_calls.append(records))

    main._auto_seed_if_empty()

    assert fast_calls == []
    assert len(live_calls) == 1
    assert live_calls[0][0]["template_id"] == "drake"


def test_falls_back_to_live_embedding_when_gemini_not_configured(monkeypatch, tmp_path):
    """Even with a valid, up-to-date precomputed file present, no
    GEMINI_API_KEY means the collection is running the local (different-
    dimension) embedding model — using precomputed Gemini vectors there
    would corrupt query-time results, so this must never happen."""
    _make_template_files(tmp_path, ["drake"])
    monkeypatch.setattr(main, "_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(main, "list_template_ids", lambda: [])
    _stub_settings_gemini_key(monkeypatch, "")  # not configured

    document = main.template_document_text("Drake", "Meme template: Drake", ["drake"])
    embeddings_file = tmp_path / "template_embeddings.json"
    embeddings_file.write_text(json.dumps({
        "drake": {"embedding": [0.1, 0.2], "document": document},
    }))
    monkeypatch.setattr(main, "_PRECOMPUTED_EMBEDDINGS_PATH", embeddings_file)

    live_calls = []
    fast_calls = []
    monkeypatch.setattr(main, "upsert_templates_batch", lambda records: live_calls.append(records))
    monkeypatch.setattr(main, "upsert_templates_batch_with_embeddings", lambda records: fast_calls.append(records))

    main._auto_seed_if_empty()

    assert fast_calls == []
    assert len(live_calls) == 1
