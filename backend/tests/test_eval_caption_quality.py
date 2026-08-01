"""
Growth Phase F — pairwise caption-quality judge. Pure-function tests only:
_build_judge_prompt (message shape), _judge_round_to_preference and
_aggregate_judgment (the position-swap bias-cancellation logic — the part
that actually needs to be correct for the eval's results to mean anything).
None of this needs GROQ_API_KEY, DATABASE_URL, or network.
"""

from __future__ import annotations

from scripts.eval_caption_quality import (
    _aggregate_judgment,
    _build_judge_prompt,
    _judge_round_to_preference,
)


def test_build_judge_prompt_shape():
    messages = _build_judge_prompt(
        "waiting for a PR review",
        "drake", {"top_text": "reviewing quickly", "bottom_text": "reviewing 3 days later"},
        "hide_the_pain_harold", {"top_text": "still waiting, it's fine"},
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    user_content = messages[1]["content"]
    assert "waiting for a PR review" in user_content
    assert "Template: drake" in user_content
    assert "reviewing 3 days later" in user_content
    assert "Template: hide_the_pain_harold" in user_content
    assert "still waiting, it's fine" in user_content


def test_judge_round_to_preference_a_is_baseline():
    assert _judge_round_to_preference("A", a_is_baseline=True) == "baseline"
    assert _judge_round_to_preference("B", a_is_baseline=True) == "candidate"
    assert _judge_round_to_preference("tie", a_is_baseline=True) == "tie"


def test_judge_round_to_preference_a_is_candidate():
    # Second round has positions swapped — A is now the candidate.
    assert _judge_round_to_preference("A", a_is_baseline=False) == "candidate"
    assert _judge_round_to_preference("B", a_is_baseline=False) == "baseline"
    assert _judge_round_to_preference("tie", a_is_baseline=False) == "tie"


def test_judge_round_to_preference_invalid_winner_is_tie():
    # A malformed judge response shouldn't crash or count as a real pick.
    assert _judge_round_to_preference("C", a_is_baseline=True) == "tie"
    assert _judge_round_to_preference("", a_is_baseline=True) == "tie"


def test_aggregate_judgment_agrees_on_baseline():
    # Round 1: baseline=A picks A (baseline). Round 2 (swapped): baseline=B picks B (baseline).
    assert _aggregate_judgment("baseline", "baseline") == "baseline"


def test_aggregate_judgment_agrees_on_candidate():
    assert _aggregate_judgment("candidate", "candidate") == "candidate"


def test_aggregate_judgment_disagreement_is_tie():
    # The judge flipped its preference when positions swapped — not a real signal.
    assert _aggregate_judgment("baseline", "candidate") == "tie"
    assert _aggregate_judgment("candidate", "baseline") == "tie"


def test_aggregate_judgment_either_round_a_tie_is_tie():
    assert _aggregate_judgment("tie", "baseline") == "tie"
    assert _aggregate_judgment("baseline", "tie") == "tie"
    assert _aggregate_judgment("tie", "tie") == "tie"
