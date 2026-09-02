"""
main.py's observability middleware: every response carries an x-request-id
(generated if the client didn't send one, echoed back if it did), and
structlog's contextvars carry that same id for the duration of the request
— covered here by spying on structlog.contextvars.bind_contextvars to
confirm the middleware actually calls it with the real per-request id.
cold_start_seconds firing exactly once per process is already covered
directly in test_telemetry.py; this only checks the middleware actually
calls the recording function during a real request.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

import telemetry
from main import app


async def test_response_carries_a_generated_request_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.headers.get("x-request-id")


async def test_response_echoes_a_client_supplied_request_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health", headers={"x-request-id": "test-request-id-123"})
    assert resp.headers["x-request-id"] == "test-request-id-123"


async def test_middleware_binds_the_real_per_request_id_into_contextvars(monkeypatch):
    import structlog

    captured = []
    original_bind = structlog.contextvars.bind_contextvars

    def spy_bind(**kwargs):
        captured.append(kwargs)
        return original_bind(**kwargs)

    monkeypatch.setattr(structlog.contextvars, "bind_contextvars", spy_bind)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health", headers={"x-request-id": "verify-binding-999"})

    assert {"request_id": "verify-binding-999"} in captured


async def test_cold_start_is_recorded_during_the_first_request(monkeypatch):
    monkeypatch.setattr(telemetry, "_cold_start_recorded", False)
    calls = []
    monkeypatch.setattr(telemetry, "record_cold_start_if_first_request", lambda: calls.append(1))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")

    assert calls == [1]
