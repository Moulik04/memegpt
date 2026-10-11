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
import math
import re
import sys
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
logger = logging.getLogger(__name__)

# The count lines below (upload_refused, router_pick, router_busy) are meant
# to be readable in the hosting platform's own log. Python only prints a
# warning to stderr by itself while nothing else is attached to the root
# logger, and where logs are exported something is, so this logger writes
# to stderr itself. Records still travel on to the root logger's handlers.
class _CurrentStderr(logging.StreamHandler):
    """Writes to whatever sys.stderr is when a record is emitted, not to the
    one that existed when this module was imported."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self):
        return sys.stderr


_platform_log = _CurrentStderr()
_platform_log.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_platform_log)

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
router_picks_total = _meter.create_counter(
    "router_picks_total",
    description="Count of template picks, by the prompt (full or retry) and model (primary or second) that made them.",
)
router_busy_total = _meter.create_counter(
    "router_busy_total",
    description="Count of picks given up on because a rate limit could not be waited out in time.",
)
moderation_rejections_total = _meter.create_counter(
    "moderation_rejections_total",
    description="Count of moderation rejections (image or text), by category.",
)
upload_refusals_total = _meter.create_counter(
    "upload_refusals_total",
    description="Count of uploaded photos a visitor was told MemeGPT can't use, by label and surface.",
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


def record_router_pick(prompt: str, model: str, template_id: str) -> None:
    """One template pick, and what made it: the full prompt or the retry
    prompt, the primary model or the second one. The two prompts are not the
    same task, so a count that mixes them says little about either. Logged
    as one line for the same reason record_upload_refusal's is. A template
    id is a catalog name, not anything the visitor wrote."""
    router_picks_total.add(1, attributes={"prompt": prompt, "model": model})
    logger.warning("router_pick prompt=%s model=%s template=%s", prompt, model, template_id)


def record_router_busy(retry_after: float) -> None:
    """A pick was not made: the provider's per-minute limit asked for a wait
    that would have run past the request's time limit."""
    router_busy_total.add(1)
    logger.warning("router_busy retry_after=%ds", math.ceil(retry_after))


def record_moderation_rejection(category: str) -> None:
    moderation_rejections_total.add(1, attributes={"category": category})


# What a refused upload is counted under. The safety check's category is
# whatever the model wrote after "UNSAFE:", which is free text and could
# describe the picture, so it is never used as it came: it is matched to one
# of these and nothing else about the photo is kept.
#   sexual, minors, violence, hate, unclear   the check's own categories
#   no_verdict     the model's reply could not be read as a verdict
#   check_failed   the check could not be run (provider error, no key)
#   other          anything else, including "unsafe" with no category
_CONTENT_LABELS = ("sexual", "minors", "violence", "hate", "unclear")
UPLOAD_REFUSAL_LABELS = frozenset({*_CONTENT_LABELS, "no_verdict", "check_failed", "other"})


def upload_refusal_label(category: str | None) -> str:
    text = (category or "").strip().lower()
    if text == "unparseable_response":
        return "no_verdict"
    if text == "moderation_unavailable":
        return "check_failed"
    first_word = re.match(r"[a-z]+", text)
    return first_word.group(0) if first_word and first_word.group(0) in _CONTENT_LABELS else "other"


def record_upload_refusal(category: str | None, surface: str | None) -> None:
    """One uploaded photo was refused. Counted, and written to the log as
    one line holding the label and the surface: no image, no file name, no
    visitor. The log line is what makes the numbers readable where no
    metrics backend is configured."""
    label = upload_refusal_label(category)
    surface = surface or "unknown"
    upload_refusals_total.add(1, attributes={"category": label, "surface": surface})
    logger.warning("upload_refused category=%s surface=%s", label, surface)


def record_cold_start_if_first_request() -> None:
    global _cold_start_recorded
    if _cold_start_recorded:
        return
    _cold_start_recorded = True
    cold_start_seconds.record(time.monotonic() - _process_start_monotonic)
