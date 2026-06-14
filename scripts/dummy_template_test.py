"""
Pillow text-compositor proof of concept.

Creates a synthetic 600×400 gradient "template" image from scratch and
runs it through the compositor with sample captions.  No real template
image is required — useful for verifying font loading and stroke rendering
without any other backend services running.

Usage:
    cd memegpt/
    python scripts/dummy_template_test.py

Output:
    scripts/dummy_output.png   — the rendered meme
"""

import sys
from pathlib import Path

# Allow importing from backend/ without installing as a package
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageDraw  # noqa: E402 — after sys.path patch
from image_processing.compositor import (  # noqa: E402
    OUTPUT_DIR,
    _draw_outlined_text,
    _resolve_font,
)

# ---------------------------------------------------------------------------
# 1. Build a synthetic template image (blue-to-purple gradient)
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 600, 400

img = Image.new("RGBA", (WIDTH, HEIGHT))
draw_bg = ImageDraw.Draw(img)

for y in range(HEIGHT):
    t = y / HEIGHT
    r = int(30 + t * 60)
    g = int(30 + t * 10)
    b = int(180 - t * 60)
    draw_bg.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))

# ---------------------------------------------------------------------------
# 2. Draw meme captions using the real compositor helpers
# ---------------------------------------------------------------------------
FONT_SIZE = int(HEIGHT * 0.09)
STROKE_W = max(1, FONT_SIZE // 18)
MARGIN = 12

font = _resolve_font(FONT_SIZE)
draw = ImageDraw.Draw(img)

top_box = {"x": MARGIN, "y": MARGIN, "width": WIDTH - 2 * MARGIN, "height": int(HEIGHT * 0.22)}
bottom_box = {
    "x": MARGIN,
    "y": int(HEIGHT * 0.76),
    "width": WIDTH - 2 * MARGIN,
    "height": int(HEIGHT * 0.22),
}

_draw_outlined_text(draw, "when the compositor works", top_box, font, stroke_width=STROKE_W)
_draw_outlined_text(
    draw,
    "but you still have no real templates yet",
    bottom_box,
    font,
    stroke_width=STROKE_W,
)

# ---------------------------------------------------------------------------
# 3. Save & report
# ---------------------------------------------------------------------------
output_path = Path(__file__).parent / "dummy_output.png"
img.save(str(output_path))

print(f"[OK] Dummy meme saved to: {output_path.resolve()}")
print(f"     Font resolved from: {font.path if hasattr(font, 'path') else 'built-in default'}")
print(f"     Image size: {WIDTH}x{HEIGHT}  Font size: {FONT_SIZE}px  Stroke: {STROKE_W}px")
