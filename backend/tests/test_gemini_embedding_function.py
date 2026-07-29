"""
Gemini embedding function — vector_db/gemini_embedding_function.py, and the
resilience wrap added to query_similar_memes()/get_similar_examples() for
this change. Every httpx call is mocked; nothing here hits the real Gemini
API or a real ChromaDB collection.
"""

from __future__ import annotations

import pytest

from config import Settings
from vector_db import chroma_client, examples_store
from vector_db import gemini_embedding_function as gef


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200, headers: dict | None = None):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _recording_fake_post(calls: list, n_embeddings: int):
    def _fake_post(url, params=None, json=None, timeout=None):
        calls.append({"url": url, "params": params, "json": json})
        return _FakeResponse({"embeddings": [{"values": [0.1, 0.2]} for _ in range(n_embeddings)]})

    return _fake_post


def _echo_count_fake_post(calls: list):
    """Returns exactly as many embeddings as the request asked for — lets a
    test assert on how requests got split into batches."""

    def _fake_post(url, params=None, json=None, timeout=None):
        calls.append({"url": url, "params": params, "json": json})
        n = len(json["requests"])
        return _FakeResponse({"embeddings": [{"values": [0.1, 0.2]} for _ in range(n)]})

    return _fake_post


def test_call_chunks_requests_over_gemini_100_item_batch_cap(monkeypatch):
    calls: list = []
    monkeypatch.setattr(gef.httpx, "post", _echo_count_fake_post(calls))

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    docs = [f"doc {i}" for i in range(150)]
    result = ef(docs)

    assert len(calls) == 2  # 100 + 50, not one 150-item call (Gemini rejects >100)
    assert len(calls[0]["json"]["requests"]) == 100
    assert len(calls[1]["json"]["requests"]) == 50
    assert len(result) == 150


def test_call_sends_one_batch_request_with_retrieval_document_task_type(monkeypatch):
    calls: list = []
    monkeypatch.setattr(gef.httpx, "post", _recording_fake_post(calls, 3))

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    result = ef(["doc one", "doc two", "doc three"])

    assert len(calls) == 1  # one HTTP call for all 3 documents, not 3 separate calls
    assert calls[0]["url"].endswith(":batchEmbedContents")
    body = calls[0]["json"]
    assert len(body["requests"]) == 3
    assert all(r["taskType"] == "RETRIEVAL_DOCUMENT" for r in body["requests"])
    assert len(result) == 3


def test_embed_query_uses_retrieval_query_task_type(monkeypatch):
    calls: list = []
    monkeypatch.setattr(gef.httpx, "post", _recording_fake_post(calls, 1))

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    ef.embed_query(["what is this meme about"])

    assert len(calls) == 1
    assert calls[0]["json"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_call_raises_on_mismatched_embedding_count(monkeypatch):
    def _fake_post(url, params=None, json=None, timeout=None):
        return _FakeResponse({"embeddings": [{"values": [0.1]}]})  # 1 returned, 2 requested

    monkeypatch.setattr(gef.httpx, "post", _fake_post)

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    with pytest.raises(ValueError):
        ef(["doc one", "doc two"])


def test_call_retries_on_429_then_succeeds(monkeypatch):
    calls: list = []

    def _fake_post(url, params=None, json=None, timeout=None):
        calls.append(url)
        if len(calls) < 3:
            return _FakeResponse({}, status_code=429)
        return _FakeResponse({"embeddings": [{"values": [0.1]}]})

    monkeypatch.setattr(gef.httpx, "post", _fake_post)
    monkeypatch.setattr(gef.time, "sleep", lambda seconds: None)  # don't actually wait in tests

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    result = ef(["one doc"])

    assert len(calls) == 3  # 2 failed attempts + 1 success
    assert len(result) == 1


def test_call_gives_up_after_max_429_retries(monkeypatch):
    calls: list = []

    def _fake_post(url, params=None, json=None, timeout=None):
        calls.append(url)
        return _FakeResponse({}, status_code=429)

    monkeypatch.setattr(gef.httpx, "post", _fake_post)
    monkeypatch.setattr(gef.time, "sleep", lambda seconds: None)

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    with pytest.raises(RuntimeError):  # _FakeResponse.raise_for_status() on the final 429
        ef(["one doc"])

    assert len(calls) == gef._MAX_429_RETRIES_DOCUMENT + 1  # 1 initial + all retries exhausted


def test_embed_query_uses_shorter_retry_budget_than_call(monkeypatch):
    """The bug this guards against: parse_intent() has a 45s total request
    timeout, but __call__'s document retry budget alone sums to 61s. If
    embed_query (the live RAG lookup path) reused that budget, a Gemini
    rate-limit blip could burn the entire request timeout on RAG retries
    alone, starving the Groq LLM call before it ever runs."""
    calls: list = []

    def _fake_post(url, params=None, json=None, timeout=None):
        calls.append(url)
        return _FakeResponse({}, status_code=429)

    monkeypatch.setattr(gef.httpx, "post", _fake_post)
    monkeypatch.setattr(gef.time, "sleep", lambda seconds: None)

    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="fake-key")
    with pytest.raises(RuntimeError):
        ef.embed_query(["one query"])

    assert len(calls) == gef._MAX_429_RETRIES_QUERY + 1
    assert gef._MAX_429_RETRIES_QUERY < gef._MAX_429_RETRIES_DOCUMENT


def test_init_requires_api_key():
    with pytest.raises(ValueError):
        gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="")


def test_get_config_never_contains_raw_key():
    ef = gef.GeminiEmbeddingFunction(model_name="gemini-embedding-2", api_key="super-secret-value")
    config = ef.get_config()
    assert "super-secret-value" not in str(config)
    assert config == {"model_name": "gemini-embedding-2", "api_key_env_var": "GEMINI_API_KEY"}


def test_get_embedding_function_returns_none_without_key():
    settings = Settings(_env_file=None, gemini_api_key="")
    assert gef.get_embedding_function(settings) is None


def test_get_embedding_function_returns_configured_instance_with_key():
    settings = Settings(
        _env_file=None, gemini_api_key="fake-key", gemini_embedding_model="gemini-embedding-2"
    )
    ef = gef.get_embedding_function(settings)
    assert ef is not None
    assert ef.model_name == "gemini-embedding-2"
    assert ef.api_key == "fake-key"


class _FailingCollection:
    """Stands in for a ChromaDB collection whose embedding function (Gemini,
    over the network) fails — used to prove the vector_db layer degrades to
    an empty list instead of propagating, preserving parse_intent()'s
    documented never-raises invariant."""

    def count(self):
        return 5

    def query(self, **kwargs):
        raise RuntimeError("Gemini API unavailable")


def test_query_similar_memes_returns_empty_list_on_embedding_failure(monkeypatch):
    monkeypatch.setattr(chroma_client, "_get_collection", lambda: _FailingCollection())
    assert chroma_client.query_similar_memes("anything") == []


def test_get_similar_examples_returns_empty_list_on_embedding_failure(monkeypatch):
    monkeypatch.setattr(examples_store, "_get_collection", lambda: _FailingCollection())
    assert examples_store.get_similar_examples("anything") == []
