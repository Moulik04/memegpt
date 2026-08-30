"""
Gemini-backed ChromaDB embedding function — raw httpx, no google-genai SDK
(matches this repo's existing no-SDK style for Groq/Anthropic/vision calls).

Fixes Render's 512MB free-tier OOM: ChromaDB's default embedding function
loads a local sentence-transformers/ONNX model in-process (empirically
measured at ~491MB peak during template seeding alone). This offloads
embedding compute to Gemini's API instead, so that model never loads.

Data-flow note: query text (a user's chat message, or a Lore-mode dump up
to max_dump_chars) and template/example documents are sent to Google's
Gemini API for embedding. This mirrors the existing Groq call already made
for LLM intent-routing — no new persistent storage, this is transient
per-request processing only. On Gemini's free tier, Google's terms permit
using submitted content to improve products and allow human review (unlike
Groq, whose no-training policy is account-wide) — a known tradeoff of
staying on the free tier.

Free-tier quota: 100 requests/minute AND a separate 1000 requests/day cap.
Both are real constraints in practice — a handful of full-catalog reseeds
plus eval runs in one day is enough to exhaust the daily cap. Unlike the
per-minute limit, there's no short retry that gets past an exhausted daily
quota; it needs real time to reset. Local dev can route around it entirely
by unsetting GEMINI_API_KEY (falls back to ChromaDB's local embedding
model, zero Gemini calls) — useful specifically when iterating on
USE_WHEN wording, since that question is independent of which embedding
backend is active.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

import circuit_breaker
from config import Settings

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT_SECONDS = 15.0
# gemini-embedding-2's free tier is rate-limited at 100 requests/minute,
# and each item in a batch counts individually against that budget — one
# _SEED_CHUNK_SIZE=20 chunk can burn a fifth of the window by itself.
#
# Two different retry budgets, not one: __call__ (documents — startup
# seeding, upsert on feedback) only ever runs in a background thread or
# via asyncio.to_thread,
# never blocking a live request, so it can afford to be patient: capped
# exponential backoff sized to outlast a full 60s rate-limit window (1, 2,
# 4, 8, 16, 30s = 61s total across 6 retries). embed_query (the live RAG
# lookup inside a real /chat/ request) must NOT reuse that budget —
# intent_router.py's parse_intent() has its own _OVERALL_TIMEOUT_SECONDS=45s
# ceiling for the ENTIRE request, and a 61s RAG-retry storm alone would
# blow straight through it before the Groq LLM call ever got a chance to
# run, wasting the whole timeout on a step that's designed to gracefully
# degrade to [] and move on (query_similar_memes/get_similar_examples
# already catch and swallow embedding failures for exactly this reason).
# A short budget here fails fast so the rest of the request still has a
# real chance to succeed.
_MAX_429_RETRIES_DOCUMENT = 6
_MAX_429_RETRIES_QUERY = 2
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0
# Gemini's batchEmbedContents hard-rejects (400) more than 100 requests in
# one call ("at most 100 requests can be in one batch") — hit whenever a
# caller embeds the full template catalog in one shot (e.g.
# scripts/find_duplicate_templates.py, which embeds all descriptions at
# once). No current production caller sends anywhere near 100 documents
# (_SEED_CHUNK_SIZE=20), but chunking transparently here means no future
# caller has to independently know about or respect this limit.
_MAX_ITEMS_PER_BATCH = 100
# One shared circuit breaker name for both __call__ (documents) and
# embed_query (queries) — they hit the same underlying Gemini quota, so a
# rate-limit signal on either is a strong signal the other would currently
# fail too. 60s ≈ Gemini's own per-minute rate-limit window.
_CIRCUIT_NAME = "gemini"
_CIRCUIT_COOLDOWN_SECONDS = 60.0


class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
    """Batches document embeds via batchEmbedContents (RETRIEVAL_DOCUMENT);
    embed_query (called automatically by ChromaDB's Collection.query() for
    query_texts) uses embedContent with RETRIEVAL_QUERY — Gemini's
    asymmetric document-vs-query embeddings, wired for free via the
    EmbeddingFunction protocol's optional embed_query() override."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        api_key_env_var: str = "GEMINI_API_KEY",
    ):
        # api_key is passed in resolved (from Settings), not re-derived via
        # os.getenv() here — pydantic-settings reads backend/.env without
        # populating the real process environment, so os.getenv() would
        # silently miss a locally-configured key even though Settings sees
        # it fine. os.getenv() is still the right fallback in
        # build_from_config() below, which runs without a Settings object.
        self.model_name = model_name
        self.api_key_env_var = api_key_env_var
        self.api_key = api_key
        if not self.api_key:
            raise ValueError(f"{api_key_env_var} must be set to use GeminiEmbeddingFunction.")

    def __call__(self, input: Documents) -> Embeddings:
        return self._embed(list(input), task_type="RETRIEVAL_DOCUMENT", max_retries=_MAX_429_RETRIES_DOCUMENT)

    def embed_query(self, input: Documents) -> Embeddings:
        return self._embed(list(input), task_type="RETRIEVAL_QUERY", max_retries=_MAX_429_RETRIES_QUERY)

    def _embed(self, texts: list[str], task_type: str, max_retries: int) -> Embeddings:
        if not texts:
            return []
        if circuit_breaker.is_open(_CIRCUIT_NAME):
            # We already know (within the last _CIRCUIT_COOLDOWN_SECONDS)
            # that Gemini is rate-limited — skip the network call and
            # retry dance entirely rather than re-discovering that on
            # every single request during an outage window.
            # query_similar_memes()/get_similar_examples() already catch
            # any exception from this call and degrade to [], so raising
            # here needs no new handling anywhere upstream.
            raise RuntimeError("Gemini circuit breaker open (cooldown from a recent rate limit)")
        embeddings: Embeddings = []
        for i in range(0, len(texts), _MAX_ITEMS_PER_BATCH):
            embeddings.extend(
                self._embed_one_batch(texts[i : i + _MAX_ITEMS_PER_BATCH], task_type, max_retries)
            )
        return embeddings

    def _embed_one_batch(self, texts: list[str], task_type: str, max_retries: int) -> Embeddings:
        model_path = f"models/{self.model_name}"
        requests_body = [
            {
                "model": model_path,
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
            }
            for text in texts
        ]
        resp = self._post_with_429_retry(model_path, requests_body, max_retries)
        resp.raise_for_status()
        circuit_breaker.reset(_CIRCUIT_NAME)  # a real success — un-gate any open circuit early
        data = resp.json()
        embeddings = data.get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise ValueError(
                f"Gemini embedding response malformed: expected {len(texts)} "
                f"embeddings, got {len(embeddings) if embeddings else 0}"
            )
        return [e["values"] for e in embeddings]

    def _post_with_429_retry(
        self, model_path: str, requests_body: list[dict], max_retries: int
    ) -> httpx.Response:
        """Startup seeding fires several batch calls back-to-back (one per
        _SEED_CHUNK_SIZE chunk), which is enough on its own to trip Gemini's
        free-tier rate limit on a fresh deploy or local run, well before any
        real per-request traffic. Bounded exponential backoff (honoring
        Retry-After when present) rides out a transient rate-limit window
        instead of raising immediately — max_retries differs by caller, see
        the module-level comment on _MAX_429_RETRIES_DOCUMENT/_QUERY.
        main.py's _auto_seed_if_empty() also wraps each chunk in its own
        try/except, so a chunk that exhausts its retry budget doesn't take
        down every remaining chunk with it."""
        for attempt in range(max_retries + 1):
            resp = httpx.post(
                f"{_API_BASE}/{model_path}:batchEmbedContents",
                params={"key": self.api_key},
                json={"requests": requests_body},
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code != 429 or attempt == max_retries:
                if resp.status_code == 429:
                    # Retries exhausted on a genuine rate limit — trip the
                    # breaker so the NEXT request (this one still has to
                    # surface the failure to its own caller) skips the
                    # whole retry dance instead of rediscovering the same
                    # rate limit from scratch.
                    circuit_breaker.trip(_CIRCUIT_NAME, _CIRCUIT_COOLDOWN_SECONDS)
                return resp
            retry_after = resp.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after
                else min(_BASE_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS)
            )
            print(
                f"[gemini_embedding_function] 429 from Gemini, "
                f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})",
                flush=True,
            )
            time.sleep(delay)
        raise AssertionError("unreachable")  # loop always returns; satisfies the type checker

    @staticmethod
    def name() -> str:
        return "gemini_embedding_2"

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]

    def get_config(self) -> dict[str, Any]:
        # Never the raw key — only the env var name, same pattern chromadb's
        # own built-in GoogleGeminiEmbeddingFunction uses, so the key never
        # lands in ChromaDB's on-disk collection metadata.
        return {"model_name": self.model_name, "api_key_env_var": self.api_key_env_var}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> GeminiEmbeddingFunction:
        model_name = config.get("model_name", "gemini-embedding-2")
        api_key_env_var = config.get("api_key_env_var", "GEMINI_API_KEY")
        api_key = os.getenv(api_key_env_var)
        if not api_key:
            raise ValueError(f"{api_key_env_var} must be set to reconstruct GeminiEmbeddingFunction.")
        return GeminiEmbeddingFunction(
            model_name=model_name, api_key=api_key, api_key_env_var=api_key_env_var
        )


def get_embedding_function(settings: Settings) -> EmbeddingFunction | None:
    """None (no GEMINI_API_KEY configured) means: omit the embedding_function
    kwarg entirely at the call site so ChromaDB's real local-default takes
    over — the zero-cost/zero-config local dev path stays unchanged."""
    if not settings.gemini_api_key:
        return None
    return GeminiEmbeddingFunction(
        model_name=settings.gemini_embedding_model,
        api_key=settings.gemini_api_key,
    )
