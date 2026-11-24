"""
Renders MemeGPT's icon set into frontend/public/.

One mark at every size: full-bleed white, an ink Anton "M" and one red
rule under it, the masthead's rule. No tile, frame or rounded corners. The
M and the rule always sit inside the centred circle 80% of the icon's
width, so Android's mask and iOS's corner rounding never reach them, and
the standard and maskable files come from the same drawing.

  favicon.ico                 16, 32, 48   16 is drawn on the pixel grid
  icon-192.png, icon-512.png               web manifest "any"
  apple-touch-icon.png        180          iOS rounds the corners itself
  icon-maskable-192.png, icon-maskable-512.png
                                           web manifest "maskable"

Run from the repo root: python scripts/render_icons.py
Needs Pillow and the committed backend/fonts/Anton-Regular.ttf.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = REPO_ROOT / "backend" / "fonts" / "Anton-Regular.ttf"
OUT_DIR = REPO_ROOT / "frontend" / "public"

# globals.css: --ink-0, --paper and --accent-color.
WHITE = (0xFF, 0xFF, 0xFF)
INK = (0x11, 0x11, 0x11)
RED = (0xCD, 0x1F, 0x35)

LETTER = "M"
SUPERSAMPLE = 8

# Only a centred circle 80% of the icon's width is sure to survive a mask.
SAFE_ZONE_RADIUS = 0.40
# The mark's corners stop short of it, so the rule's ends keep some white
# around them after a circular mask.
MARK_REACH = 0.36

# The rule and the gap above it, as shares of the letter's height.
RULE_SHARE = 0.11
GAP_SHARE = 0.09

# At 16px a scaled-down letter turns grey, so this size is drawn on the
# pixel grid: "#" is ink, "r" is the red rule.
MARK_16 = (
    "##....##",
    "###..###",
    "########",
    "##.##.##",
    "##....##",
    "##....##",
    "##....##",
    "........",
    ".rrrrrr.",
)
# Nine rows can't centre on sixteen; the rule is a pixel shorter at each
# end so its corners stay inside the safe zone.
MARK_16_ORIGIN = (4, 4)


def _glyph(height: int) -> Image.Image:
    """The letter's ink alone, as a mask exactly `height` pixels tall.
    Measured from the drawn pixels: Pillow's bounding box includes the
    letter's side bearings, which would leave the rule wider than the M."""
    probe = ImageFont.truetype(str(FONT_PATH), 1000)
    _, top, _, bottom = probe.getbbox(LETTER)
    font = ImageFont.truetype(str(FONT_PATH), round(1000 * height / (bottom - top)))
    _, _, right, bottom = font.getbbox(LETTER)
    canvas = Image.new("L", (right + height, bottom + height), 0)
    ImageDraw.Draw(canvas).text((height // 2, height // 2), LETTER, font=font, fill=255)
    return canvas.crop(canvas.getbbox())


def render(size: int) -> tuple[Image.Image, float]:
    """The mark at one size. Returns it and how far its corner sits from the
    centre, as a share of the icon's width.

    The layout is worked out in the icon's own pixels and snapped to them,
    so the rule and the letter's edges land on whole pixels and stay crisp
    at 32 and 48. The drawing is made 8 times larger and averaged down,
    which softens only the diagonals."""
    aspect_glyph = _glyph(1000)
    aspect = aspect_glyph.width / aspect_glyph.height
    stack = 1 + GAP_SHARE + RULE_SHARE
    # The mark is aspect*h wide and h*stack tall; its corner may reach
    # MARK_REACH of the width.
    letter_h = math.floor(MARK_REACH * size / math.hypot(aspect / 2, stack / 2))
    letter_w = round(aspect * letter_h)
    gap = max(1, round(letter_h * GAP_SHARE))
    rule = max(1, round(letter_h * RULE_SHARE))
    mark_h = letter_h + gap + rule
    top = round((size - mark_h) / 2)
    side = round((size - letter_w) / 2)

    big = size * SUPERSAMPLE
    img = Image.new("RGB", (big, big), WHITE)
    glyph = _glyph(letter_h * SUPERSAMPLE).resize((letter_w * SUPERSAMPLE, letter_h * SUPERSAMPLE), Image.LANCZOS)
    img.paste(Image.new("RGB", glyph.size, INK), (side * SUPERSAMPLE, top * SUPERSAMPLE), glyph)
    rule_top = (top + letter_h + gap) * SUPERSAMPLE
    ImageDraw.Draw(img).rectangle(
        (side * SUPERSAMPLE, rule_top, (side + letter_w) * SUPERSAMPLE - 1, rule_top + rule * SUPERSAMPLE - 1),
        fill=RED,
    )

    corner_x = max(size / 2 - side, side + letter_w - size / 2)
    corner_y = max(size / 2 - top, top + mark_h - size / 2)
    reach = math.hypot(corner_x, corner_y) / size
    return img.resize((size, size), Image.BOX), reach


def render_16() -> tuple[Image.Image, float]:
    img = Image.new("RGB", (16, 16), WHITE)
    ox, oy = MARK_16_ORIGIN
    colors = {"#": INK, "r": RED}
    far = 0.0
    for y, row in enumerate(MARK_16):
        for x, cell in enumerate(row):
            if cell in colors:
                img.putpixel((ox + x, oy + y), colors[cell])
                # The pixel's far corner, from the icon's centre.
                dx = max(abs(ox + x - 8), abs(ox + x + 1 - 8))
                dy = max(abs(oy + y - 8), abs(oy + y + 1 - 8))
                far = max(far, math.hypot(dx, dy))
    return img, far / 16


def _check(name: str, reach: float) -> None:
    if reach > SAFE_ZONE_RADIUS:
        raise SystemExit(f"{name}: the mark reaches {reach:.3f} of the width, outside the safe zone.")
    print(f"{name}: mark reaches {reach:.3f}, safe zone ends at {SAFE_ZONE_RADIUS}")


def main() -> None:
    if not FONT_PATH.exists():
        raise SystemExit(f"Missing {FONT_PATH}.")

    sixteen, reach = render_16()
    _check("favicon 16", reach)
    favicon = {16: sixteen}
    for size in (32, 48):
        favicon[size], reach = render(size)
        _check(f"favicon {size}", reach)
    favicon[48].save(
        OUT_DIR / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in favicon],
        append_images=[favicon[16], favicon[32]],
    )

    for size in (192, 512):
        icon, reach = render(size)
        _check(f"icon-{size}.png", reach)
        icon.save(OUT_DIR / f"icon-{size}.png", optimize=True)
        icon.save(OUT_DIR / f"icon-maskable-{size}.png", optimize=True)

    apple, reach = render(180)
    _check("apple-touch-icon.png", reach)
    apple.save(OUT_DIR / "apple-touch-icon.png", optimize=True)
    # Older iOS versions and some crawlers ask for this name instead.
    shutil.copyfile(OUT_DIR / "apple-touch-icon.png", OUT_DIR / "apple-touch-icon-precomposed.png")

    print(f"Wrote the icon set to {OUT_DIR}")


if __name__ == "__main__":
    main()
