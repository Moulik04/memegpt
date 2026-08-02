"""
main.py's _auto_seed_if_empty() — real production incident (Growth Phase G,
Discord integration): Gemini rate-limiting during startup seeding exhausted
the retry budget on one chunk, raising uncaught and killing every
remaining chunk. Because the collection wasn't empty anymore (an earlier
chunk had already landed), the old "only seed when fully empty" guard meant
the catalog stayed permanently partial — this function would never run
again. Covers the fix: not gated on emptiness, and one failing chunk
doesn't prevent the rest from being attempted.
"""

from __future__ import annotations

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
