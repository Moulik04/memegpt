"""
Growth Phase G — GIF template rendering. Real Pillow-level tests (not
mocked) against a synthetic multi-frame GIF fixture built in the test
itself — no real template file needed. compose_meme()'s GIF branch is
exercised by monkeypatching TEMPLATES_DIR + get_config (the same
monkeypatch-the-module-reference pattern test_compositor.py already uses
for get_settings), so this doesn't touch the real backend/templates/
catalog at all.
"""

from __future__ import annotations

from PIL import Image

from config import Settings
from image_processing.compositor import (
    _GIF_MAX_DIMENSION_PX,
    _GIF_MAX_FRAMES,
    compose_meme,
)
from image_processing.template_configs import TemplateConfig, TextBoxConfig


def _fake_settings(monkeypatch, **overrides):
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    monkeypatch.setattr("storage.get_settings", lambda: settings)
    return settings


def _write_synthetic_gif(path, n_frames: int, size: tuple[int, int]) -> None:
    frames = [Image.new("RGB", size, ((i * 7) % 255, 60, 90)) for i in range(n_frames)]
    frames[0].save(path, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)


def _gif_config(template_id: str) -> TemplateConfig:
    return TemplateConfig(
        template_id=template_id,
        text_boxes=[
            TextBoxConfig("top_text", x_pct=5, y_pct=2, w_pct=90, h_pct=20, font_size_pct=7),
            TextBoxConfig("bottom_text", x_pct=5, y_pct=78, w_pct=90, h_pct=20, font_size_pct=7),
        ],
        is_gif=True,
    )


def _use_fixture_gif(monkeypatch, tmp_path, n_frames=10, size=(200, 200), template_id="test_gif_template"):
    monkeypatch.setattr("image_processing.compositor.TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr("image_processing.compositor.get_config", lambda tid: _gif_config(tid))
    _write_synthetic_gif(tmp_path / f"{template_id}.gif", n_frames, size)
    return template_id


async def test_gif_template_produces_animated_gif_output(monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    tid = _use_fixture_gif(monkeypatch, tmp_path, n_frames=8)

    saved = await compose_meme(tid, {"top_text": "TOP", "bottom_text": "BOTTOM"})

    assert saved.url.endswith(".gif")
    assert saved.path is not None
    out = Image.open(saved.path)
    assert out.n_frames == 8  # under the cap, nothing dropped


async def test_gif_frame_count_is_capped(monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    tid = _use_fixture_gif(monkeypatch, tmp_path, n_frames=_GIF_MAX_FRAMES + 15)

    saved = await compose_meme(tid, {"top_text": "TOP", "bottom_text": "BOTTOM"})

    out = Image.open(saved.path)
    assert out.n_frames == _GIF_MAX_FRAMES


async def test_gif_dimension_is_capped(monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    oversized = (_GIF_MAX_DIMENSION_PX + 400, _GIF_MAX_DIMENSION_PX + 200)
    tid = _use_fixture_gif(monkeypatch, tmp_path, n_frames=3, size=oversized)

    saved = await compose_meme(tid, {"top_text": "TOP", "bottom_text": "BOTTOM"})

    out = Image.open(saved.path)
    assert max(out.size) <= _GIF_MAX_DIMENSION_PX


async def test_gif_watermark_changes_output_bytes(monkeypatch, tmp_path):
    tid = _use_fixture_gif(monkeypatch, tmp_path, n_frames=5)

    _fake_settings(monkeypatch, watermark_enabled=True)
    with_mark = await compose_meme(tid, {"top_text": "a", "bottom_text": "b"})
    on_bytes = with_mark.path.read_bytes()

    _fake_settings(monkeypatch, watermark_enabled=False)
    without_mark = await compose_meme(tid, {"top_text": "a", "bottom_text": "b"})
    off_bytes = without_mark.path.read_bytes()

    assert on_bytes != off_bytes


async def test_gif_uses_gif_content_type_on_r2(monkeypatch, tmp_path):
    """Confirms the extension/content_type params actually reach
    save_meme() — checked via the R2 path (mocked client, matching
    test_storage.py's precedent) since local-disk save doesn't expose
    ContentType directly."""
    tid = _use_fixture_gif(monkeypatch, tmp_path, n_frames=3)
    settings = Settings(
        _env_file=None,
        r2_account_id="acct", r2_access_key_id="key", r2_secret_access_key="secret",
        r2_bucket="bucket", r2_public_base_url="https://pub-xxx.r2.dev",
    )
    monkeypatch.setattr("image_processing.compositor.get_settings", lambda: settings)
    monkeypatch.setattr("storage.get_settings", lambda: settings)

    calls = []

    class FakeR2Client:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("storage._r2_client", lambda s: FakeR2Client())

    saved = await compose_meme(tid, {"top_text": "a", "bottom_text": "b"})

    assert saved.url.endswith(".gif")
    assert len(calls) == 1
    assert calls[0]["ContentType"] == "image/gif"
    assert calls[0]["Key"].endswith(".gif")


async def test_static_templates_unaffected_by_gif_branch(monkeypatch):
    """Sanity check that the static path (is_gif=False, the dataclass
    default) still goes through the untouched PNG pipeline — real
    drake.jpg template, nothing monkeypatched about TEMPLATES_DIR/get_config."""
    _fake_settings(monkeypatch)
    saved = await compose_meme("drake", {"top_text": "old way", "bottom_text": "new way"})
    assert saved.url.endswith(".png")
