"""
Observability — metrics + structured logs, pushed to Grafana Cloud via
OTLP. See docs/superpowers/specs/2026-09-01-cloud-migration-phase4-
observability-design.md for the full design and why this is push-based
(OpenTelemetry) rather than the master doc's originally-named
prometheus-fastapi-instrumentator: Cloud Run scales to zero, so a
pull-based /metrics endpoint has nothing reliably scraping it.

Configured entirely at import time, keyed off settings.grafana_otlp_endpoint
— empty (the default, and every test environment) means every instrument
created below binds to OpenTelemetry's built-in no-op providers, matching
this codebase's existing "empty = disabled" convention (config.py). No
recording function anywhere needs its own disabled-check as a result.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import structlog
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource

import circuit_breaker
from config import get_settings

_settings = get_settings()
_resource = Resource.create({"service.name": "memegpt-backend"})

if _settings.grafana_otlp_endpoint and _settings.grafana_otlp_token:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    _headers = {"Authorization": _settings.grafana_otlp_token}

    _metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=f"{_settings.grafana_otlp_endpoint}/v1/metrics",
            headers=_headers,
        ),
        export_interval_millis=15_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=_resource, metric_readers=[_metric_reader]))

    _logger_provider = LoggerProvider(resource=_resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=f"{_settings.grafana_otlp_endpoint}/v1/logs",
                headers=_headers,
            )
        )
    )
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=_logger_provider))
    logging.getLogger("opentelemetry").propagate = False

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

_meter = metrics.get_meter("memegpt-backend")

meme_generation_duration_seconds = _meter.create_histogram(
    "meme_generation_duration_seconds",
    unit="s",
    description="Time to compose one meme image, by surface.",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60],
)
template_selection_total = _meter.create_counter(
    "template_selection_total",
    description="Count of times each catalog template was selected.",
)
intent_parse_failures_total = _meter.create_counter(
    "intent_parse_failures_total",
    description="Count of failed intent-parse attempts, by stage.",
)
hard_fallback_hits_total = _meter.create_counter(
    "hard_fallback_hits_total",
    description="Count of times parse_intent returned the hardcoded fallback meme.",
)
moderation_rejections_total = _meter.create_counter(
    "moderation_rejections_total",
    description="Count of moderation rejections (image or text), by category.",
)
cold_start_seconds = _meter.create_histogram(
    "cold_start_seconds",
    unit="s",
    description="Time from process import to the first request an instance serves.",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60],
)


def _circuit_breaker_observations(options: CallbackOptions) -> Iterable[Observation]:
    settings = get_settings()
    names = [f"groq:{settings.groq_model}"]
    if settings.groq_fallback_model and settings.groq_fallback_model != settings.groq_model:
        names.append(f"groq:{settings.groq_fallback_model}")
    names.append("gemini")
    for name in names:
        yield Observation(1 if circuit_breaker.is_open(name) else 0, {"breaker": name})


_meter.create_observable_gauge(
    "circuit_breaker_state",
    callbacks=[_circuit_breaker_observations],
    description="1 if the named circuit is currently open (tripped), else 0.",
)

_process_start_monotonic = time.monotonic()
_cold_start_recorded = False


def record_meme_generation(surface: str | None, duration_seconds: float) -> None:
    meme_generation_duration_seconds.record(duration_seconds, attributes={"surface": surface or "unknown"})


def record_template_selection(template_id: str) -> None:
    template_selection_total.add(1, attributes={"template_id": template_id})


def record_intent_parse_failure(stage: str) -> None:
    intent_parse_failures_total.add(1, attributes={"stage": stage})


def record_hard_fallback_hit() -> None:
    hard_fallback_hits_total.add(1)


def record_moderation_rejection(category: str) -> None:
    moderation_rejections_total.add(1, attributes={"category": category})


def record_cold_start_if_first_request() -> None:
    global _cold_start_recorded
    if _cold_start_recorded:
        return
    _cold_start_recorded = True
    cold_start_seconds.record(time.monotonic() - _process_start_monotonic)
