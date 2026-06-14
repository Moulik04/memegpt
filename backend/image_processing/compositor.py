"""
Pillow-based meme text compositor.

Responsibilities:
  - Load a template image from disk.
  - Resolve an Impact/Arial font at an appropriate size.
  - Wrap text to fit strictly within a bounding box (no overflow).
  - Draw outlined (stroke) text — classic meme style.
  - Save the composed image to static/generated/ and return its URL or path.
"""

from __future__ import annotations

import os
import textwrap
import uuid
from pathlib import Path
from typing import Union

from PIL import Image, ImageDraw, ImageFont

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = BACKEND_ROOT / "fonts"
TEMPLATES_DIR = BACKEND_ROOT / "templates"
OUTPUT_DIR = BACKEND_ROOT / "static" / "generated"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Candidate font names searched in FONTS_DIR first, then common system paths
_FONT_CANDIDATES = [
    "Impact.ttf",
    "impact.ttf",
    "Arial Bold.ttf",
    "Arial.ttf",
    "arial.ttf",
]

_SYSTEM_FONT_PATHS = [
    # macOS
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    # Linux (wine / msttcorefonts)
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _resolve_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES:
        candidate = FONTS_DIR / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)

    for path in _SYSTEM_FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    # Last resort — Pillow's built-in bitmap font (no size control)
    return ImageFont.load_default()


def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: dict[str, int],
    font: ImageFont.FreeTypeFont,
    fill: str = "#FFFFFF",
    stroke_fill: str = "#000000",
    stroke_width: int = 2,
    uppercase: bool = True,
) -> None:
    """
    Draw `text` inside `box` (x, y, width, height), auto-wrapping to stay
    within the box and centered both horizontally and vertically.
    Stroke is drawn first so fill sits cleanly on top.
    """
    if uppercase:
        text = text.upper()

    x, y, w, h = box["x"], box["y"], box["width"], box["height"]

    # Estimate how many chars fit per line
    avg_char_px = font.getlength("A")
    chars_per_line = max(1, int(w / avg_char_px))
    lines = textwrap.wrap(text, width=chars_per_line) or [""]

    line_height = font.size + 4
    total_text_h = line_height * len(lines)

    # Vertical centering within the bounding box
    start_y = y + max(0, (h - total_text_h) // 2)

    for i, line in enumerate(lines):
        line_px = font.getlength(line)
        line_x = x + max(0, (w - line_px) // 2)
        line_y = start_y + i * line_height

        # Stroke pass — 8-directional offsets
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((line_x + dx, line_y + dy), line, font=font, fill=stroke_fill)

        # Fill pass
        draw.text((line_x, line_y), line, font=font, fill=fill)


async def compose_meme(
    template_id: str,
    top_text: str,
    bottom_text: str,
    return_path: bool = False,
) -> Union[str, Path]:
    """
    Compose a meme from `template_id` with the given captions.

    Returns a URL string suitable for the `/static/generated/` mount by
    default, or an absolute Path when `return_path=True`.
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

    # Derive font size proportional to image height (~7 %)
    font_size = max(20, int(img_h * 0.07))
    font = _resolve_font(font_size)
    stroke_width = max(1, font_size // 20)
    margin = max(8, int(img_h * 0.02))

    # Default two-zone layout — top 20 % / bottom 20 %
    top_box = {
        "x": margin,
        "y": margin,
        "width": img_w - 2 * margin,
        "height": int(img_h * 0.20),
    }
    bottom_box = {
        "x": margin,
        "y": int(img_h * 0.78),
        "width": img_w - 2 * margin,
        "height": int(img_h * 0.20),
    }

    if top_text.strip():
        _draw_outlined_text(draw, top_text, top_box, font, stroke_width=stroke_width)
    if bottom_text.strip():
        _draw_outlined_text(draw, bottom_text, bottom_box, font, stroke_width=stroke_width)

    # Save as PNG to preserve transparency / quality
    output_name = f"{template_id}_{uuid.uuid4().hex[:8]}.png"
    output_path = OUTPUT_DIR / output_name
    img.save(str(output_path), format="PNG")

    if return_path:
        return output_path

    return f"/static/generated/{output_name}"
