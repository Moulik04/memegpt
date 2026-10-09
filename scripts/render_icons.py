"""
Renders MemeGPT's icon set into frontend/public/.

One mark at every size: an accent tile, a white Anton "M", and the black
caption stroke from globals.css (.caption puts 0.08em on the outline, so
0.04em shows outside the letter).

  favicon.ico                 16, 32, 48   rounded tile
  icon-192.png, icon-512.png               rounded tile, web manifest "any"
  apple-touch-icon.png        180          plain square, iOS rounds it itself
  icon-maskable-192.png, icon-maskable-512.png
                                           full bleed, letter inside the
                                           safe zone Android may crop to

Run from the repo root: python scripts/render_icons.py
Needs Pillow and backend/fonts/Anton-Regular.ttf (the backend's build
downloads the font, see backend/Dockerfile).
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = REPO_ROOT / "backend" / "fonts" / "Anton-Regular.ttf"
OUT_DIR = REPO_ROOT / "frontend" / "public"

ACCENT = (0xF5, 0x4F, 0x1B, 255)  # --accent-color
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)  # --stroke
CLEAR = (0, 0, 0, 0)

LETTER = "M"
SUPERSAMPLE = 8

TILE_RADIUS = 0.22  # of the icon's width
STROKE_EM = 0.04
# A 0.04em stroke is under a pixel below 48px and disappears into the
# tile, so the favicon sizes get a slightly heavier one.
FAVICON_STROKE_EM = 0.055

# Letter height as a share of the icon's width.
TILE_LETTER = 0.56
MASKABLE_LETTER = 0.40

# Android crops a maskable icon to whatever shape the launcher uses. Only a
# centred circle 80% of the icon's width is guaranteed to survive.
SAFE_ZONE_RADIUS = 0.40

# At 16px a scaled-down letter is a grey smudge, so this size is drawn on
# the pixel grid. "#" is the letter. The stroke is added around it the way
# the compositor does it, one pixel in each of the eight directions.
LETTER_16 = (
    "##......##",
    "###....###",
    "####..####",
    "##.####.##",
    "##..##..##",
    "##......##",
    "##......##",
    "##......##",
    "##......##",
)
LETTER_16_ORIGIN = (3, 3)


def _tile(size: int, rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), CLEAR if rounded else ACCENT)
    if rounded:
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, size - 1, size - 1), radius=round(size * TILE_RADIUS), fill=ACCENT
        )
    return img


def _font_for_height(height: float) -> ImageFont.FreeTypeFont:
    probe = ImageFont.truetype(str(FONT_PATH), 1000)
    _, top, _, bottom = probe.getbbox(LETTER)
    return ImageFont.truetype(str(FONT_PATH), round(1000 * height / (bottom - top)))


def _draw_letter(img: Image.Image, letter_share: float, stroke_em: float) -> float:
    """Centres the letter on the image. Returns how far its stroked corner
    sits from the centre, as a share of the image's width."""
    size = img.width
    font = _font_for_height(size * letter_share)
    stroke = max(1, round(font.size * stroke_em))
    left, top, right, bottom = font.getbbox(LETTER)
    width, height = right - left, bottom - top
    ImageDraw.Draw(img).text(
        ((size - width) / 2 - left, (size - height) / 2 - top),
        LETTER,
        font=font,
        fill=WHITE,
        stroke_width=stroke,
        stroke_fill=BLACK,
    )
    return math.hypot(width / 2 + stroke, height / 2 + stroke) / size


def render(size: int, *, rounded: bool, letter_share: float = TILE_LETTER,
           stroke_em: float = STROKE_EM) -> tuple[Image.Image, float]:
    big = _tile(size * SUPERSAMPLE, rounded)
    reach = _draw_letter(big, letter_share, stroke_em)
    return big.resize((size, size), Image.LANCZOS), reach


def render_16() -> Image.Image:
    img = _tile(16 * SUPERSAMPLE, rounded=True).resize((16, 16), Image.LANCZOS)
    ox, oy = LETTER_16_ORIGIN
    letter = {
        (ox + x, oy + y)
        for y, row in enumerate(LETTER_16)
        for x, cell in enumerate(row)
        if cell == "#"
    }
    stroke = {
        (x + dx, y + dy)
        for x, y in letter
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    } - letter
    for xy in stroke:
        img.putpixel(xy, BLACK)
    for xy in letter:
        img.putpixel(xy, WHITE)
    return img


def main() -> None:
    if not FONT_PATH.exists():
        raise SystemExit(f"Missing {FONT_PATH}. The backend's build downloads it.")

    favicon = {
        16: render_16(),
        32: render(32, rounded=True, stroke_em=FAVICON_STROKE_EM)[0],
        48: render(48, rounded=True, stroke_em=FAVICON_STROKE_EM)[0],
    }
    favicon[48].save(
        OUT_DIR / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in favicon],
        append_images=[favicon[16], favicon[32]],
    )

    for size in (192, 512):
        render(size, rounded=True)[0].save(OUT_DIR / f"icon-{size}.png", optimize=True)

    # No alpha channel: iOS paints transparent pixels black.
    apple, _ = render(180, rounded=False)
    apple.convert("RGB").save(OUT_DIR / "apple-touch-icon.png", optimize=True)
    # Older iOS versions and some crawlers ask for this name instead.
    shutil.copyfile(OUT_DIR / "apple-touch-icon.png", OUT_DIR / "apple-touch-icon-precomposed.png")

    for size in (192, 512):
        icon, reach = render(size, rounded=False, letter_share=MASKABLE_LETTER)
        if reach > SAFE_ZONE_RADIUS:
            raise SystemExit(f"The letter reaches {reach:.3f} of the width, outside the safe zone.")
        icon.convert("RGB").save(OUT_DIR / f"icon-maskable-{size}.png", optimize=True)
        print(f"icon-maskable-{size}.png: letter reaches {reach:.3f}, safe zone ends at {SAFE_ZONE_RADIUS}")

    print(f"Wrote the icon set to {OUT_DIR}")


if __name__ == "__main__":
    main()
