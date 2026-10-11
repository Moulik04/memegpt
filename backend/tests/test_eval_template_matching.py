"""
scripts/eval_template_matching.py reports its accuracy per prompt, because
the full prompt and the retry prompt are different tasks and one number for
both hid that until 2026-10-10. Pure functions only: no model call.
"""

from __future__ import annotations

import pytest

from scripts.eval_template_matching import (
    ProviderError,
    accuracy_by_prompt,
    outcome_tag,
    parse_args,
    reply_counts,
    reply_kind,
)


def _row(prompt, hit, fallback=False, busy=False) -> dict:
    return {"prompt": prompt, "final_hit": hit, "is_fallback": fallback, "is_busy": busy}


def test_accuracy_is_counted_separately_for_each_prompt():
    rows = [_row("full", True), _row("full", True), _row("full", False), _row("retry", False)]

    assert accuracy_by_prompt(rows) == {"full": (2, 3), "retry": (0, 1)}


def test_a_prompt_that_answered_nothing_is_not_listed():
    assert accuracy_by_prompt([_row("full", True)]) == {"full": (1, 1)}


def test_rows_with_no_pick_are_left_out_of_every_prompts_count():
    rows = [_row("full", True), _row(None, False, fallback=True), _row(None, False, fallback=True, busy=True)]

    assert accuracy_by_prompt(rows) == {"full": (1, 1)}


def test_a_busy_case_is_told_apart_from_a_canned_fallback_and_a_wrong_pick():
    assert outcome_tag(_row("full", True)) == "OK"
    assert outcome_tag(_row("retry", False)) == "WRONG"
    assert outcome_tag(_row(None, False, fallback=True)) == "FALLBACK"
    assert outcome_tag(_row(None, False, fallback=True, busy=True)) == "BUSY"


def test_pacing_defaults_to_ten_seconds_and_can_be_raised():
    assert parse_args([]).pacing == 10
    assert parse_args(["--pacing", "28"]).pacing == 28


def test_pacing_cannot_be_lowered():
    with pytest.raises(SystemExit):
        parse_args(["--pacing", "5"])


# --- the second model, forced -------------------------------------------------


def test_the_second_model_is_only_forced_when_asked():
    assert parse_args([]).second_model is False
    assert parse_args(["--second-model", "--pacing", "28"]).second_model is True


def test_a_reply_is_sorted_by_whether_it_is_json_at_all():
    assert reply_kind('{"template_id": "drake", "texts": {}}') == "clean"
    assert reply_kind('```json\n{"template_id": "drake"}\n```') == "clean"  # fences are stripped, as the router does
    assert reply_kind('{"template_id": "drake", "texts": {"a": "b"}} {"reasoning": "x"}') == "malformed"
    assert reply_kind("Sure! Here is the meme:") == "malformed"
    assert reply_kind("") == "empty"
    assert reply_kind(None) == "none"  # no reply was received at all (busy)


def test_replies_are_counted_by_kind():
    rows = [{"reply": "clean"}, {"reply": "clean"}, {"reply": "malformed"}, {"reply": "empty"}, {"reply": "none"}]

    assert reply_counts(rows) == {"clean": 2, "malformed": 1, "empty": 1, "none": 1}


def test_a_canned_fallback_is_never_shown_as_a_right_answer():
    """The canned meme is hide_the_pain_harold, which one golden case
    expects. A fallback on that case is still not a pick."""
    assert outcome_tag(_row(None, True, fallback=True)) == "FALLBACK"
    assert outcome_tag(_row(None, True, fallback=True, busy=True)) == "BUSY"


def test_output_the_provider_rejected_as_invalid_json_counts_as_malformed():
    """With response_format json_object Groq answers 400 json_validate_failed
    instead of handing back what the model wrote. No reply reaches the
    router, but it was the model's JSON that was wrong."""
    assert reply_kind(ProviderError(400, "json_validate_failed")) == "malformed"


def test_any_other_provider_error_is_its_own_kind():
    assert reply_kind(ProviderError(503, None)) == "error"
    assert reply_kind(ProviderError(400, "model_decommissioned")) == "error"
