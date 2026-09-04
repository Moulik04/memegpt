"""
Growth Phase E — trend pipeline. Pure-function tests only: diff_new_candidates,
insert_use_when_entries, and _merge_embeddings (no network, no filesystem —
all operate on in-memory data). None need GROQ_API_KEY, GEMINI_API_KEY,
DATABASE_URL, or network, matching this repo's existing zero-secrets test
contract.
"""

from __future__ import annotations

import pytest

from scripts.trend_pipeline import _merge_embeddings, diff_new_candidates, insert_use_when_entries


def test_diff_new_candidates_filters_out_existing_by_slug():
    # existing_slugs is the actual template_ids on disk, which this pure
    # function compares against a raw slugify() of Imgflip's display name —
    # NOT our curated short ids (e.g. real "Drake Hotline Bling" slugifies
    # to "drake_hotline_bling", not "drake"; see diff_new_candidates'
    # docstring). Fixture data reflects that reality, not the curated names.
    memes = [
        {"name": "Existing Template Name", "url": "https://i.imgflip.com/a.jpg"},
        {"name": "Some Brand New Meme!!", "url": "https://i.imgflip.com/new.jpg"},
    ]
    existing = {"existing_template_name", "evil_kermit"}
    result = diff_new_candidates(memes, existing)
    assert [m["name"] for m in result] == ["Some Brand New Meme!!"]


def test_diff_new_candidates_slugifies_consistently():
    # "Two Buttons!" -> "two_buttons" — punctuation/casing shouldn't cause a
    # false "new" positive against an existing template_id.
    memes = [{"name": "Two Buttons!", "url": "x"}]
    existing = {"two_buttons"}
    assert diff_new_candidates(memes, existing) == []


def test_diff_new_candidates_empty_when_nothing_new():
    memes = [{"name": "Existing Template Name", "url": "x"}]
    existing = {"existing_template_name"}
    assert diff_new_candidates(memes, existing) == []


_FIXTURE_SOURCE = '''\
"""Module docstring."""

_SOME_OTHER_DICT = {
    "a": "b",
}

USE_WHEN: dict[str, str] = {
    "drake": "SETTLED PREFERENCE: a description.",
    "evil_kermit": "INNER DEVIL DIALOGUE: a description.",
}


def _build_template_catalog(template_ids):
    return {}
'''


def test_insert_use_when_entries_adds_before_closing_brace():
    result = insert_use_when_entries(_FIXTURE_SOURCE, {"new_template": "A DRAFTED ENTRY."})
    assert '"new_template": "A DRAFTED ENTRY."' in result
    # Existing entries untouched, in original order.
    assert '"drake": "SETTLED PREFERENCE: a description."' in result
    assert '"evil_kermit": "INNER DEVIL DIALOGUE: a description."' in result
    # The new entry lands inside the USE_WHEN dict, before its closing
    # brace, not inside the unrelated _SOME_OTHER_DICT above it.
    use_when_start = result.index("USE_WHEN: dict[str, str] = {")
    new_entry_pos = result.index('"new_template"')
    use_when_close = result.index("\n}", use_when_start)
    assert use_when_start < new_entry_pos < use_when_close
    # Untouched trailing content (the function below) still present verbatim.
    assert "def _build_template_catalog(template_ids):" in result


def test_insert_use_when_entries_multiple_new_entries():
    result = insert_use_when_entries(
        _FIXTURE_SOURCE, {"first_new": "FIRST.", "second_new": "SECOND."}
    )
    assert '"first_new": "FIRST."' in result
    assert '"second_new": "SECOND."' in result


def test_insert_use_when_entries_raises_if_opening_marker_missing():
    broken_source = _FIXTURE_SOURCE.replace("USE_WHEN: dict[str, str] = {", "USE_WHEN = {")
    with pytest.raises(ValueError):
        insert_use_when_entries(broken_source, {"x": "y"})


def test_insert_use_when_entries_raises_if_marker_appears_twice():
    doubled = _FIXTURE_SOURCE + "\n" + _FIXTURE_SOURCE
    with pytest.raises(ValueError):
        insert_use_when_entries(doubled, {"x": "y"})


def test_insert_use_when_entries_refuses_a_result_that_would_not_compile():
    # tid is inserted into the f-string directly, unescaped (only the value
    # goes through json.dumps) — slugify() can never produce a tid with a
    # quote in it in real use, but this proves the compile-check safety net
    # added alongside full automation actually catches it if something ever
    # did, rather than silently writing broken Python to intent_router.py
    # with no human downstream to notice.
    with pytest.raises(ValueError, match="no longer compiles"):
        insert_use_when_entries(_FIXTURE_SOURCE, {'bad"tid': "A DRAFTED ENTRY."})


def test_merge_embeddings_adds_new_entries_keeps_existing():
    existing = {"drake": {"embedding": [0.1, 0.2], "document": "Drake. desc. Tags: drake."}}
    new = {"new_template": {"embedding": [0.3, 0.4], "document": "New Template. desc. Tags: new_template."}}
    merged = _merge_embeddings(existing, new)
    assert merged["drake"] == existing["drake"]
    assert merged["new_template"] == new["new_template"]


def test_merge_embeddings_new_entry_overwrites_same_id():
    existing = {"drake": {"embedding": [0.1], "document": "old"}}
    new = {"drake": {"embedding": [0.9], "document": "new"}}
    merged = _merge_embeddings(existing, new)
    assert merged["drake"]["document"] == "new"
