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
Groq, whose no-training policy is account-wide); this tradeoff was
disclosed to and accepted by the project owner. See CLAUDE.md's Vector DB
section.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from config import Settings

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT_SECONDS = 15.0
# gemini-embedding-2's free tier is rate-limited at 100 requests/minute.
# Empirically confirmed live: an isolated single-text call succeeds
# immediately even right after a 20-text batchEmbedContents call gets
# 429'd — consistent with each item in a batch counting individually
# against that 100/minute budget, so one _SEED_CHUNK_SIZE=20 chunk can
# burn a fifth of the window by itself. Retries are cheap here — this only
# runs in a background seeding thread or via asyncio.to_thread, never
# blocking a live request — so the schedule is sized to comfortably
# outlast a full 60s rate-limit window rather than give up early: capped
# exponential backoff (1, 2, 4, 8, 16, 30s = 61s total across 6 retries).
_MAX_429_RETRIES = 6
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0


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
        return self._embed(list(input), task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, input: Documents) -> Embeddings:
        return self._embed(list(input), task_type="RETRIEVAL_QUERY")

    def _embed(self, texts: list[str], task_type: str) -> Embeddings:
        if not texts:
            return []
        model_path = f"models/{self.model_name}"
        requests_body = [
            {
                "model": model_path,
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
            }
            for text in texts
        ]
        resp = self._post_with_429_retry(model_path, requests_body)
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise ValueError(
                f"Gemini embedding response malformed: expected {len(texts)} "
                f"embeddings, got {len(embeddings) if embeddings else 0}"
            )
        return [e["values"] for e in embeddings]

    def _post_with_429_retry(self, model_path: str, requests_body: list[dict]) -> httpx.Response:
        """Startup seeding fires several batch calls back-to-back (one per
        _SEED_CHUNK_SIZE chunk) — empirically confirmed live, this alone is
        enough to trip Gemini's free-tier rate limit on the very first
        deploy/local run, well before any real per-request traffic. A bare
        raise here would crash the whole seed (no per-chunk try/except in
        main.py's _auto_seed_if_empty()), leaving the app stuck on the small
        hardcoded template fallback until the next restart. Bounded
        exponential backoff (honoring Retry-After when present) rides out a
        transient rate-limit window instead."""
        for attempt in range(_MAX_429_RETRIES + 1):
            resp = httpx.post(
                f"{_API_BASE}/{model_path}:batchEmbedContents",
                params={"key": self.api_key},
                json={"requests": requests_body},
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code != 429 or attempt == _MAX_429_RETRIES:
                return resp
            retry_after = resp.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after
                else min(_BASE_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS)
            )
            print(
                f"[gemini_embedding_function] 429 from Gemini, "
                f"retrying in {delay:.1f}s (attempt {attempt + 1}/{_MAX_429_RETRIES})",
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
    def build_from_config(config: dict[str, Any]) -> "GeminiEmbeddingFunction":
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
