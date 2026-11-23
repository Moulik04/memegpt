"""
Make numbers each caption box on the bare template from the positions GET
/explain/ sends. Those positions must be exactly where compose_meme draws
the text, or a marker points at one spot and the caption lands in another.

The comparison runs the real compositor on every template on disk (GIFs
included, where frames can be scaled down) and records each box it draws,
then checks the API's percentages reproduce those pixels on that image.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import image_processing.compositor as compositor
from main import app
from routers.explain import _text_boxes_for
from storage import SavedMeme

_TEMPLATE_IDS = sorted(
    p.stem for p in compositor.TEMPLATES_DIR.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
)


def test_every_template_on_disk_is_checked():
    assert len(_TEMPLATE_IDS) >= 100


@pytest.mark.parametrize("template_id", _TEMPLATE_IDS)
async def test_api_box_positions_match_where_the_compositor_draws(monkeypatch, template_id):
    drawn: dict[str, tuple[dict[str, int], tuple[int, int]]] = {}

    def record(draw, text, box_cfg, pixel_box, img_h):
        # The first frame is enough: every GIF frame has the same size.
        drawn.setdefault(box_cfg.label, (pixel_box, draw.im.size))

    async def no_save(*args, **kwargs):
        return SavedMeme(meme_id="test", url="/static/generated/test.png", path=None)

    monkeypatch.setattr(compositor, "_draw_text_in_box", record)
    monkeypatch.setattr(compositor, "_finalize_and_save", no_save)
    monkeypatch.setattr(compositor, "_finalize_and_save_gif", no_save)

    boxes = _text_boxes_for(template_id)
    await compositor.compose_meme(template_id, {box.label: "caption" for box in boxes})

    assert [box.label for box in boxes] == list(drawn), "the API lists a box the compositor doesn't draw, or misses one"
    assert 1 <= len(boxes) <= 5
    for box in boxes:
        pixel_box, (img_w, img_h) = drawn[box.label]
        assert pixel_box == {
            "x": int(img_w * box.x_pct / 100),
            "y": int(img_h * box.y_pct / 100),
            "width": int(img_w * box.w_pct / 100),
            "height": int(img_h * box.h_pct / 100),
        }, f"{template_id}/{box.label}"


async def test_the_template_list_sends_the_positions(monkeypatch):
    monkeypatch.setattr(
        "routers.explain.list_all_template_records",
        lambda: [{"template_id": "drake", "name": "Drake", "description": "", "tags": [], "usage_count": 0}],
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/explain/")

    assert resp.status_code == 200
    boxes = resp.json()[0]["text_boxes"]
    assert boxes and {"label", "description", "x_pct", "y_pct", "w_pct", "h_pct"} <= set(boxes[0])
