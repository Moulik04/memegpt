"""
Lore's big-paste ceiling (max_dump_chars) — server-side clamp truncates
rather than rejects, since a partial highlight reel from the first N
characters is still useful.
"""

from __future__ import annotations

from routers.chat import _clamp_dump_text


def test_short_text_unaffected():
    text = "waiting for my PR to get reviewed"
    assert _clamp_dump_text(text) == text


def test_none_stays_none():
    assert _clamp_dump_text(None) is None


def test_oversized_text_clamped_not_rejected(monkeypatch):
    from config import Settings

    fake_settings = Settings(max_dump_chars=100)
    monkeypatch.setattr("routers.chat.get_settings", lambda: fake_settings)

    long_text = "x" * 500
    result = _clamp_dump_text(long_text)
    assert result is not None
    assert len(result) == 100
    assert result == "x" * 100
