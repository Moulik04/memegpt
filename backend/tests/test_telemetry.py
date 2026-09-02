"""
telemetry.py's recording functions must be safe to call unconditionally
from every call site added in this plan, in every environment — including
every test environment, which runs with GRAFANA_OTLP_ENDPOINT/TOKEN unset
(see conftest.py's _isolate_settings_from_real_dot_env). This covers that
no-op-safety directly, plus the circuit_breaker_state observable gauge's
callback logic in isolation (its real emission path only runs on an actual
OTLP export tick, which these tests don't need to trigger).
"""

from __future__ import annotations

import circuit_breaker as cb
import telemetry
from config import Settings


def test_record_meme_generation_is_safe_and_labels_surface(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.meme_generation_duration_seconds,
        "record",
        lambda value, attributes=None: captured.append((value, attributes)),
    )
    telemetry.record_meme_generation("chat", 1.5)
    assert captured == [(1.5, {"surface": "chat"})]


def test_record_meme_generation_defaults_missing_surface_to_unknown(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.meme_generation_duration_seconds,
        "record",
        lambda value, attributes=None: captured.append(attributes),
    )
    telemetry.record_meme_generation(None, 1.0)
    assert captured == [{"surface": "unknown"}]


def test_record_template_selection_is_safe(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.template_selection_total,
        "add",
        lambda value, attributes=None: captured.append((value, attributes)),
    )
    telemetry.record_template_selection("drake")
    assert captured == [(1, {"template_id": "drake"})]


def test_record_intent_parse_failure_is_safe(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.intent_parse_failures_total,
        "add",
        lambda value, attributes=None: captured.append(attributes),
    )
    telemetry.record_intent_parse_failure("retry")
    assert captured == [{"stage": "retry"}]


def test_record_hard_fallback_hit_is_safe(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.hard_fallback_hits_total, "add", lambda value, attributes=None: captured.append(value)
    )
    telemetry.record_hard_fallback_hit()
    assert captured == [1]


def test_record_moderation_rejection_is_safe(monkeypatch):
    captured = []
    monkeypatch.setattr(
        telemetry.moderation_rejections_total,
        "add",
        lambda value, attributes=None: captured.append(attributes),
    )
    telemetry.record_moderation_rejection("hate")
    assert captured == [{"category": "hate"}]


def test_cold_start_records_exactly_once(monkeypatch):
    monkeypatch.setattr(telemetry, "_cold_start_recorded", False)
    captured = []
    monkeypatch.setattr(
        telemetry.cold_start_seconds, "record", lambda value, attributes=None: captured.append(value)
    )
    telemetry.record_cold_start_if_first_request()
    telemetry.record_cold_start_if_first_request()
    telemetry.record_cold_start_if_first_request()
    assert len(captured) == 1


def test_circuit_breaker_observations_covers_groq_primary_fallback_and_gemini(monkeypatch):
    monkeypatch.setattr(
        telemetry,
        "get_settings",
        lambda: Settings(_env_file=None, groq_model="model-a", groq_fallback_model="model-b"),
    )
    cb.trip("groq:model-a", cooldown_seconds=60)

    observations = list(telemetry._circuit_breaker_observations(None))
    by_breaker = {obs.attributes["breaker"]: obs.value for obs in observations}

    assert by_breaker == {"groq:model-a": 1, "groq:model-b": 0, "gemini": 0}


def test_circuit_breaker_observations_skips_duplicate_when_no_distinct_fallback(monkeypatch):
    monkeypatch.setattr(
        telemetry,
        "get_settings",
        lambda: Settings(_env_file=None, groq_model="model-a", groq_fallback_model=""),
    )
    observations = list(telemetry._circuit_breaker_observations(None))
    breakers = [obs.attributes["breaker"] for obs in observations]
    assert breakers == ["groq:model-a", "gemini"]
