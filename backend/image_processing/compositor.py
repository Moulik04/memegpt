"""
Pillow-based meme text compositor.

- Loads a template image from disk.
- Resolves an Impact/Arial font at the right size per text box.
- Wraps text to fit strictly within each bounding box.
- Draws outlined (stroke) text — classic meme style.
- Uses per-template TextBoxConfig from template_configs.py so each
  meme format gets the right layout (Drake right-half, Gru 4-panel, etc.)
"""

from __future__ import annotations

import os
import textwrap
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Union

from PIL import Image, ImageDraw, ImageFont

from image_processing.template_configs import TextBoxConfig, get_config

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = BACKEND_ROOT / "fonts"
TEMPLATES_DIR = BACKEND_ROOT / "templates"
OUTPUT_DIR = BACKEND_ROOT / "static" / "generated"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_FONT_CANDIDATES = [
    "Impact.ttf", "impact.ttf",
    "Arial Bold.ttf", "Arial.ttf", "arial.ttf",
]

_SYSTEM_FONT_PATHS = [
    # macOS
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    # Linux / Docker — Anton is Impact-style, downloaded in Dockerfile
    "/usr/share/fonts/truetype/Anton-Regular.ttf",
    # Linux fallback — installed via fonts-liberation apt package
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
]


@lru_cache(maxsize=32)
def _resolve_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES:
        candidate = FONTS_DIR / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    for path in _SYSTEM_FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_cfg: TextBoxConfig,
    pixel_box: dict[str, int],
    img_h: int,
) -> None:
    """
    Render `text` inside `pixel_box` using the style from `box_cfg`.
    Wraps lines to fit width, centers both axes, draws stroke then fill.
    """
    if not text.strip():
        return

    display = text.upper() if box_cfg.uppercase else text

    font_size = box_cfg.font_size_px(img_h)
    font = _resolve_font(font_size)
    stroke_width = max(2, font_size // 12)

    x, y, w, h = pixel_box["x"], pixel_box["y"], pixel_box["width"], pixel_box["height"]

    # Auto-shrink font if text is too wide
    while font_size > 10:
        avg_char_px = font.getlength("A")
        chars_per_line = max(1, int(w / avg_char_px))
        lines = textwrap.wrap(display, width=chars_per_line) or [display]
        line_height = font_size + 4
        if line_height * len(lines) <= h:
            break
        font_size -= 2
        font = _resolve_font(font_size)
        stroke_width = max(2, font_size // 12)

    avg_char_px = font.getlength("A")
    chars_per_line = max(1, int(w / avg_char_px))
    lines = textwrap.wrap(display, width=chars_per_line) or [display]
    line_height = font_size + 4
    total_h = line_height * len(lines)

    start_y = y + max(0, (h - total_h) // 2)

    for i, line in enumerate(lines):
        line_px = font.getlength(line)
        line_x = x + max(0, (w - int(line_px)) // 2)
        line_y = start_y + i * line_height

        # Stroke pass
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text(
                        (line_x + dx, line_y + dy),
                        line, font=font, fill=box_cfg.stroke_color,
                    )
        # Fill pass
        draw.text((line_x, line_y), line, font=font, fill=box_cfg.font_color)


async def compose_meme(
    template_id: str,
    texts: dict[str, str],
    return_path: bool = False,
) -> Union[str, Path]:
    """
    Compose a meme from `template_id`, placing each entry in `texts`
    into its named text box according to the template's layout config.

    `texts` maps text box label → caption string, e.g.:
        {"rejected_option": "Python 2", "approved_option": "Python 3"}
        {"other_woman": "new framework", "boyfriend": "me", "girlfriend": "deadline"}

    Returns a URL string (for the /static/generated/ mount) by default,
    or an absolute Path when return_path=True.
    """
    # Resolve template image
    template_path: Path | None = None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = TEMPLATES_DIR / f"{template_id}{ext}"
        if candidate.exists():
            template_path = candidate
            break

    if template_path is None:
        raise FileNotFoundError(
            f"No template image found for '{template_id}' in {TEMPLATES_DIR}"
        )

    img = Image.open(template_path).convert("RGBA")
    img_w, img_h = img.size
    draw = ImageDraw.Draw(img)

    config = get_config(template_id)

    for box_cfg in config.text_boxes:
        text = texts.get(box_cfg.label, "")
        if not text.strip():
            continue
        pixel_box = box_cfg.to_pixels(img_w, img_h)
        _draw_text_in_box(draw, text, box_cfg, pixel_box, img_h)

    output_name = f"{template_id}_{uuid.uuid4().hex[:8]}.png"
    output_path = OUTPUT_DIR / output_name
    img.save(str(output_path), format="PNG")

    if return_path:
        return output_path

    return f"/static/generated/{output_name}"
