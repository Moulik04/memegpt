"""
Renders the site-wide link preview into frontend/public/link-preview.png.

1200 x 630, laid out like the landing cover: the wordmark over a red rule,
the headline and the one-line description on the left, and a real lead
meme on the grey mat to the right. Shared meme pages keep previewing the
meme itself; this is only for links to the rest of the site.

Run from the repo root: python scripts/render_link_preview.py
Needs Pillow and the committed fonts in backend/fonts. No network.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONTS = REPO_ROOT / "backend" / "fonts"
PUBLIC = REPO_ROOT / "frontend" / "public"
OUT = PUBLIC / "link-preview.png"

# The landing's Chat story: "day 1 of the gym vs day 2".
LEAD = PUBLIC / "landing" / "loop_9.png"

WIDTH, HEIGHT = 1200, 630
SUPERSAMPLE = 2

# globals.css: --ink-0, --paper, --accent-color, --meme-mat, --meme-edge.
WHITE = (0xFF, 0xFF, 0xFF)
INK = (0x11, 0x11, 0x11)
RED = (0xCD, 0x1F, 0x35)
MAT = (0xE7, 0xE8, 0xEA)
EDGE = (0xBF, 0xC1, 0xC4)

HEADLINE = ("The group chat", "has a front page.")
LINE = "A chatbot that only replies in memes."
WORDMARK = "MemeGPT"

MARGIN = 64
MASTHEAD_H = 104
RULE_H = 3
MAT_PAD = 16


def _anton(px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / "Anton-Regular.ttf"), round(px * SUPERSAMPLE))


def _archivo(px: float, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / "Archivo-Variable.ttf"), round(px * SUPERSAMPLE))
    font.set_variation_by_axes([weight])
    return font


def main() -> None:
    s = SUPERSAMPLE
    img = Image.new("RGB", (WIDTH * s, HEIGHT * s), WHITE)
    draw = ImageDraw.Draw(img)

    # Masthead: wordmark, then the full-width red rule.
    mark = _anton(44)
    _, top, _, bottom = draw.textbbox((0, 0), WORDMARK, font=mark)
    draw.text((MARGIN * s, (MASTHEAD_H * s - (bottom - top)) / 2 - top), WORDMARK, font=mark, fill=INK)
    draw.rectangle((0, MASTHEAD_H * s, WIDTH * s, (MASTHEAD_H + RULE_H) * s - 1), fill=RED)

    # Lead meme on the mat, right column, at its own aspect ratio.
    body_top = MASTHEAD_H + RULE_H
    lead = Image.open(LEAD).convert("RGB")
    box_w, box_h = 470, HEIGHT - body_top - 2 * 48
    scale = min((box_w - 2 * MAT_PAD - 2) / lead.width, (box_h - 2 * MAT_PAD - 2) / lead.height)
    meme_w, meme_h = round(lead.width * scale), round(lead.height * scale)
    mat_w, mat_h = meme_w + 2 * MAT_PAD + 2, meme_h + 2 * MAT_PAD + 2
    mat_x = WIDTH - MARGIN - mat_w
    mat_y = body_top + (HEIGHT - body_top - mat_h) // 2
    draw.rectangle((mat_x * s, mat_y * s, (mat_x + mat_w) * s - 1, (mat_y + mat_h) * s - 1), fill=EDGE)
    draw.rectangle(
        ((mat_x + 1) * s, (mat_y + 1) * s, (mat_x + mat_w - 1) * s - 1, (mat_y + mat_h - 1) * s - 1), fill=MAT
    )
    meme_x, meme_y = mat_x + 1 + MAT_PAD, mat_y + 1 + MAT_PAD
    draw.rectangle(
        ((meme_x - 1) * s, (meme_y - 1) * s, (meme_x + meme_w + 1) * s - 1, (meme_y + meme_h + 1) * s - 1),
        fill=EDGE,
    )
    img.paste(lead.resize((meme_w * s, meme_h * s), Image.LANCZOS), (meme_x * s, meme_y * s))

    # Headline and line, left column, centred on the meme as a block.
    column_w = mat_x - MARGIN - 48
    headline = _anton(104)
    while max(draw.textlength(row, font=headline) for row in HEADLINE) > column_w * s:
        headline = _anton(headline.size / s - 2)
    line = _archivo(30, 500)
    lead_px = round(headline.size * 0.98)
    ascent = draw.textbbox((0, 0), HEADLINE[0], font=headline)[1]
    head_h = lead_px * (len(HEADLINE) - 1) + draw.textbbox((0, 0), HEADLINE[-1], font=headline)[3] - ascent
    gap = 28 * s
    line_box = draw.textbbox((0, 0), LINE, font=line)
    block_h = head_h + gap + (line_box[3] - line_box[1])
    y = (mat_y + mat_h / 2) * s - block_h / 2
    for i, row in enumerate(HEADLINE):
        draw.text((MARGIN * s, y + i * lead_px - ascent), row, font=headline, fill=INK)
    draw.text((MARGIN * s, y + head_h + gap - line_box[1]), LINE, font=line, fill=INK)
    if draw.textlength(LINE, font=line) > column_w * s:
        raise SystemExit("The line doesn't fit the left column.")

    img.resize((WIDTH, HEIGHT), Image.LANCZOS).save(OUT, optimize=True)
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
