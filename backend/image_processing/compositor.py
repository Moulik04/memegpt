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

import io
import os
import textwrap
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

from config import get_settings
from image_processing.template_configs import DEFAULT_BOXES, TextBoxConfig, get_config
from schemas import ArcStats
from storage import SavedMeme, generate_meme_id, save_meme

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = BACKEND_ROOT / "fonts"
TEMPLATES_DIR = BACKEND_ROOT / "templates"

_TEMPLATE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def resolve_template_image_path(template_id: str) -> Path | None:
    """The shared "find this template's source image on disk" lookup —
    compose_meme() uses it to render, and Growth Phase D's Arc feature
    (arc/copy.py) uses the same resolution to build a public URL for the
    "signature template" thumbnail, so both agree on which file backs a
    given template_id."""
    for ext in _TEMPLATE_IMAGE_EXTENSIONS:
        candidate = TEMPLATES_DIR / f"{template_id}{ext}"
        if candidate.exists():
            return candidate
    return None


_FONT_CANDIDATES = [
    "Anton-Regular.ttf",          # downloaded in Render build / drop in backend/fonts/
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


def _draw_watermark(img: Image.Image) -> None:
    """Small brand mark, bottom-right, drawn AFTER captions and independent
    of the TextBoxConfig layout system — it must never reposition or shrink
    a caption box. Uses its own RGBA-mode ImageDraw regardless of how the
    caller's own draw object was constructed, so semi-transparent alpha
    actually blends instead of being drawn opaque."""
    settings = get_settings()
    if not settings.watermark_enabled:
        return

    img_w, img_h = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    font_size = max(12, int(img_h * 0.035))
    font = _resolve_font(font_size)
    stroke_width = max(1, font_size // 14)
    text = settings.watermark_text

    text_w = font.getlength(text)
    padding = max(6, int(img_h * 0.02))
    x = img_w - int(text_w) - padding
    y = img_h - font_size - padding

    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 130))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 170))


async def _finalize_and_save(img: Image.Image) -> SavedMeme:
    """Shared tail for both compose functions: draw the watermark, encode
    to PNG bytes in memory (never touches disk directly — storage.save_meme
    decides local-disk vs R2), embed the provenance tEXt tag (best-effort —
    most platforms strip PNG metadata on re-encode, so the visible
    watermark is the durable mark), and persist. meme_id is generated here
    (not inside storage.save_meme) specifically so it can be embedded in
    the PNG bytes before they're handed off."""
    meme_id = generate_meme_id()
    _draw_watermark(img)

    info = PngInfo()
    info.add_text("memegpt_id", meme_id)
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info)

    return await save_meme(buf.getvalue(), meme_id=meme_id)


async def compose_meme(
    template_id: str,
    texts: dict[str, str],
) -> SavedMeme:
    """
    Compose a meme from `template_id`, placing each entry in `texts`
    into its named text box according to the template's layout config.

    `texts` maps text box label → caption string, e.g.:
        {"rejected_option": "Python 2", "approved_option": "Python 3"}
        {"other_woman": "new framework", "boyfriend": "me", "girlfriend": "deadline"}

    Returns a SavedMeme (meme_id, url, path) — path is None when stored on
    R2 rather than local disk.
    """
    template_path = resolve_template_image_path(template_id)
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

    return await _finalize_and_save(img)


async def compose_meme_on_image(
    image: Image.Image,
    texts: dict[str, str],
) -> SavedMeme:
    """
    Phase 2 canvas mode — captions the user's OWN photo directly using the
    generic top/bottom DEFAULT_BOXES layout, rather than looking up a fixed
    template_id in TEMPLATES_DIR.

    Draws a translucent dark scrim behind each box before the stroke+fill
    text pass — arbitrary user photos have no hand-tuned safe zone the way
    catalog templates do (nearly every non-DEFAULT_BOXES entry in
    template_configs.py exists specifically because generic placement
    doesn't work for that image's composition); the scrim guarantees
    legibility regardless of what's underneath, at effectively zero cost,
    without waiting on a future face-detection pass. Reuses
    _resolve_font/_draw_text_in_box unchanged — both are already generic
    over arbitrary image dimensions.
    """
    img = image.convert("RGBA")
    img_w, img_h = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    for box_cfg in DEFAULT_BOXES:
        text = texts.get(box_cfg.label, "")
        if not text.strip():
            continue
        pixel_box = box_cfg.to_pixels(img_w, img_h)
        x, y, w, h = pixel_box["x"], pixel_box["y"], pixel_box["width"], pixel_box["height"]
        draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0, 120))
        _draw_text_in_box(draw, text, box_cfg, pixel_box, img_h)

    return await _finalize_and_save(img)


# --- Growth Phase D — Arc share card ---
#
# Its own from-scratch rendering path (not a catalog template, not a user's
# own photo) — designed in Artifacts with the project owner (concept v2,
# approved) before being ported here. The visual language (violet -> magenta
# -> pink aura glow behind a gradient-filled hero number, a mono-flavored
# roast readout, a tier badge) mirrors that approved concept as closely as
# Pillow's toolset allows; it isn't a pixel-exact port of the CSS mockup —
# Pillow has no blend modes or native gradient-fill text, both approximated
# below with a hand-rolled radial glow and a masked gradient-text helper.

_ARC_CARD_SIZE = (1080, 1350)
_ARC_VOID = (7, 6, 12)
_ARC_VIOLET = (168, 85, 247)
_ARC_MAGENTA = (232, 121, 249)
_ARC_PINK = (255, 93, 177)
_ARC_CYAN = (34, 211, 238)
_ARC_MUTED = (155, 144, 181)
_ARC_MUTED_DIM = (107, 99, 131)
_ARC_TEXT = (246, 244, 251)


def _make_radial_glow(size: int, color: tuple[int, int, int]) -> Image.Image:
    """A soft radial glow blob — Pillow has no built-in radial gradient, so
    this hand-rolls one at a small resolution (cheap: 64x64 = 4096 pixels)
    and upscales with smoothing, rather than looping over every pixel at
    full card resolution."""
    small = 64
    grad = Image.new("L", (small, small), 0)
    pixels = grad.load()
    cx = cy = small / 2
    max_dist = small / 2
    for y in range(small):
        for x in range(small):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            pixels[x, y] = max(0, 255 - int(255 * dist / max_dist))
    grad = grad.resize((size, size), Image.BICUBIC)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    color_layer = Image.new("RGBA", (size, size), color + (255,))
    return Image.composite(color_layer, glow, grad)


def _draw_gradient_text(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    top_y: int,
    colors: list[tuple[int, int, int]],
) -> int:
    """Renders `text` filled with a left-to-right gradient across `colors`
    — Pillow has no native gradient-fill text, so this renders the glyphs
    as an alpha mask, builds a gradient strip the same size, and composites
    the gradient through the mask. Returns the rendered text height so the
    caller can lay out whatever comes next."""
    bbox = font.getbbox(text)
    w, h = max(bbox[2] - bbox[0], 1), max(bbox[3] - bbox[1], 1)

    mask_img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask_img).text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    gradient = Image.new("RGB", (w, h))
    grad_draw = ImageDraw.Draw(gradient)
    n = len(colors)
    for x in range(w):
        t = x / max(1, w - 1)
        seg = min(int(t * (n - 1)), n - 2)
        local_t = t * (n - 1) - seg
        c0, c1 = colors[seg], colors[seg + 1]
        color = tuple(int(c0[i] + (c1[i] - c0[i]) * local_t) for i in range(3))
        grad_draw.line([(x, 0), (x, h)], fill=color)

    img.paste(gradient, (center_x - w // 2, top_y), mask_img)
    return h


def _draw_centered_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    top_y: int,
    max_width: int,
) -> None:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or font.getlength(trial) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    y = top_y
    for line in lines:
        line_w = int(font.getlength(line))
        draw.text((center_x - line_w // 2, y), line, font=font, fill=_ARC_TEXT)
        y += int(font.size * 1.25)


async def compose_arc_card(stats: ArcStats) -> SavedMeme:
    """Renders one Arc share card from an already-computed ArcStats (see
    arc/copy.py's build_arc_stats) and hands off to the same
    _finalize_and_save every other meme uses — watermark, provenance tag,
    save — so it gets a real meme_id/url and therefore an /m/{id}, exactly
    like a catalog meme or a canvas-mode one."""
    w, h = _ARC_CARD_SIZE
    img = Image.new("RGBA", (w, h), _ARC_VOID + (255,))

    # Aura glow behind the hero number — two overlapping blurred blobs
    # (violet, then a tighter magenta core) approximating the layered CSS
    # radial-gradient + conic-gradient ring from the approved concept.
    center_x, center_y = w // 2, int(h * 0.40)
    glow = _make_radial_glow(int(w * 0.78), _ARC_VIOLET)
    glow = glow.filter(ImageFilter.GaussianBlur(glow.width // 14))
    img.alpha_composite(glow, (center_x - glow.width // 2, center_y - glow.height // 2))
    glow2 = _make_radial_glow(int(w * 0.50), _ARC_MAGENTA)
    glow2 = glow2.filter(ImageFilter.GaussianBlur(glow2.width // 12))
    img.alpha_composite(glow2, (center_x - glow2.width // 2, center_y - glow2.height // 2))

    draw = ImageDraw.Draw(img, "RGBA")
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=64, outline=_ARC_VIOLET + (90,), width=3)

    # Wordmark + tier badge
    word_font = _resolve_font(int(h * 0.028))
    draw.text((int(w * 0.08), int(h * 0.05)), "MEMEGPT ARC.", font=word_font, fill=_ARC_TEXT)

    if stats.tier:
        tier_text = stats.tier.upper()
        tier_font = _resolve_font(int(h * 0.018))
        tier_w = int(tier_font.getlength(tier_text))
        pad_x, pad_y = 22, 14
        badge_x1 = w - int(w * 0.08) - tier_w - pad_x * 2
        badge_y0 = int(h * 0.045)
        draw.rounded_rectangle(
            [badge_x1, badge_y0, badge_x1 + tier_w + pad_x * 2, badge_y0 + tier_font.size + pad_y],
            radius=999, fill=_ARC_VIOLET + (60,), outline=_ARC_MAGENTA + (140,), width=2,
        )
        draw.text((badge_x1 + pad_x, badge_y0 + pad_y // 2), tier_text, font=tier_font, fill=_ARC_TEXT)

    # Season / date-span line
    if stats.period_label:
        season_font = _resolve_font(int(h * 0.017))
        draw.text((int(w * 0.08), int(h * 0.10)), stats.period_label.upper(), font=season_font, fill=_ARC_MUTED)

    # Hero: "+<aura>" gradient number
    aura_font = _resolve_font(int(h * 0.11))
    hero_top = int(h * 0.30)
    text_h = _draw_gradient_text(
        img, f"+{stats.aura:,}", aura_font, center_x, hero_top,
        [_ARC_VIOLET, _ARC_MAGENTA, _ARC_PINK],
    )
    label_font = _resolve_font(int(h * 0.015))
    label_text = "A U R A   F A R M E D"
    label_w = int(label_font.getlength(label_text))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.text((center_x - label_w // 2, hero_top + text_h + 14), label_text, font=label_font, fill=_ARC_CYAN)

    # Readout lines
    readout_font = _resolve_font(int(h * 0.019))
    lines = [f"{stats.total_memes} memes generated"]
    if stats.top_templates:
        top = stats.top_templates[0]
        lines.append(f"top template: {top.display_name}  {top.roast}")
    if stats.busiest_time_label:
        lines.append(f"busiest: {stats.busiest_time_label}  {stats.hour_roast or ''}".strip())
    lines.append(f"chat / lore: {stats.chat_count} / {stats.lore_count}  {stats.split_roast or ''}".strip())
    lines.append(f"longest streak: {stats.longest_streak_days} days")

    y = int(h * 0.56)
    draw.line([(int(w * 0.08), y), (int(w * 0.92), y)], fill=_ARC_VIOLET + (60,), width=2)
    y += 20
    for line in lines:
        draw.text((int(w * 0.08), y), f"› {line}", font=readout_font, fill=_ARC_MUTED)
        y += int(readout_font.size * 1.7)

    # Verdict
    if stats.verdict:
        verdict_font = _resolve_font(int(h * 0.024))
        _draw_centered_wrapped(draw, stats.verdict.upper(), verdict_font, center_x, y + 16, int(w * 0.82))

    # Footer
    foot_font = _resolve_font(int(h * 0.014))
    foot_y = h - int(h * 0.05)
    draw.text((int(w * 0.08), foot_y), "memegpt", font=foot_font, fill=_ARC_MUTED)
    handle = "memegpt.app/arc"
    handle_w = int(foot_font.getlength(handle))
    draw.text((w - int(w * 0.08) - handle_w, foot_y), handle, font=foot_font, fill=_ARC_MUTED_DIM)

    return await _finalize_and_save(img)
