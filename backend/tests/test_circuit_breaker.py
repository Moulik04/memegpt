"""
circuit_breaker.py — the shared primitive behind both the Gemini and Groq
resilience improvements (see test_gemini_embedding_function.py and
test_intent_router.py for their respective integrations). Pure, in-memory,
zero network/secrets.
"""

from __future__ import annotations

import circuit_breaker as cb


def test_closed_by_default():
    assert cb.is_open("never_tripped") is False


def test_trip_opens_the_circuit():
    cb.trip("service_a", cooldown_seconds=60)
    assert cb.is_open("service_a") is True


def test_reset_closes_the_circuit_immediately():
    cb.trip("service_b", cooldown_seconds=60)
    cb.reset("service_b")
    assert cb.is_open("service_b") is False


def test_reset_on_a_never_tripped_circuit_is_a_no_op():
    cb.reset("never_tripped_either")  # must not raise
    assert cb.is_open("never_tripped_either") is False


def test_cooldown_expires_on_its_own(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(cb.time, "monotonic", lambda: fake_time[0])

    cb.trip("service_c", cooldown_seconds=60)
    assert cb.is_open("service_c") is True

    fake_time[0] += 61  # past the cooldown window
    assert cb.is_open("service_c") is False


def test_independent_circuits_dont_interfere():
    cb.trip("groq:model-a", cooldown_seconds=60)
    assert cb.is_open("groq:model-a") is True
    assert cb.is_open("groq:model-b") is False


def test_retripping_extends_the_cooldown(monkeypatch):
    fake_time = [2000.0]
    monkeypatch.setattr(cb.time, "monotonic", lambda: fake_time[0])

    cb.trip("service_d", cooldown_seconds=60)
    fake_time[0] += 50  # still within the first cooldown
    cb.trip("service_d", cooldown_seconds=60)  # re-trip, e.g. a second failure
    fake_time[0] += 55  # would be past the FIRST trip's window, not the second's
    assert cb.is_open("service_d") is True
