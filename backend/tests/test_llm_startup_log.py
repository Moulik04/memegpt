"""Startup log line naming the active LLM provider.

call_llm() quietly drops from Groq to Ollama when GROQ_API_KEY is empty, and
text/image moderation fails closed without that same key. Without a startup
line the only symptom is a stock fallback meme long after boot.
"""

from config import Settings
from nlp.llm_client import describe_llm_provider, log_llm_provider


def _settings(**overrides) -> Settings:
    base = {"llm_provider": "ollama", "groq_api_key": ""}
    return Settings(_env_file=None, **{**base, **overrides})


def test_groq_with_key_is_ok_and_names_the_model():
    level, message = describe_llm_provider(_settings(llm_provider="groq", groq_api_key="k"))
    assert level == "info"
    assert "groq" in message
    assert "qwen/qwen3.8-27b" in message


def test_groq_without_key_warns_about_silent_ollama_fallthrough():
    level, message = describe_llm_provider(_settings(llm_provider="groq", groq_api_key=""))
    assert level == "warning"
    assert "GROQ_API_KEY" in message
    assert "Ollama" in message
    assert "refused" in message


def test_ollama_with_groq_key_is_ok():
    level, message = describe_llm_provider(_settings(llm_provider="ollama", groq_api_key="k"))
    assert level == "info"
    assert "ollama" in message
    assert "qwen3:8b" in message


def test_ollama_without_groq_key_warns_that_moderation_will_refuse():
    level, message = describe_llm_provider(_settings(llm_provider="ollama", groq_api_key=""))
    assert level == "warning"
    assert "Make" in message and "uploads" in message


def test_message_never_contains_the_key_value():
    _, message = describe_llm_provider(_settings(llm_provider="groq", groq_api_key="gsk_super_secret"))
    assert "gsk_super_secret" not in message


def test_log_llm_provider_prints_a_loud_banner_for_warnings(capsys):
    log_llm_provider(_settings(llm_provider="groq", groq_api_key=""))
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "GROQ_API_KEY" in out


def test_log_llm_provider_prints_a_single_plain_line_when_healthy(capsys):
    log_llm_provider(_settings(llm_provider="groq", groq_api_key="k"))
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert "WARNING" not in out[0]
