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
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence
from PIL.PngImagePlugin import PngInfo

from config import get_settings
from image_processing.template_configs import DEFAULT_BOXES, TextBoxConfig, get_config
from schemas import ArcStats
from storage import SavedMeme, generate_meme_id, save_meme

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = BACKEND_ROOT / "fonts"
TEMPLATES_DIR = BACKEND_ROOT / "templates"

_TEMPLATE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# Growth Phase G — GIF templates. Caps keep per-meme render time and output
# size predictably bounded up front, rather than a post-hoc retry loop.
_GIF_MAX_FRAMES = 30
_GIF_MAX_DIMENSION_PX = 480
_GIF_MAX_OUTPUT_BYTES = 8 * 1024 * 1024  # ~8MB, per the growth spec


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


def template_image_url(template_id: str) -> str | None:
    """Public URL for a template's raw source image, servable as-is via
    main.py's /static/templates mount. Was arc/copy.py's private
    _template_image_url (Growth Phase D's "signature template" thumbnail)
    until Phase 4 gave the explain/list-templates endpoint a second real
    consumer — moved here, next to the file-resolution logic both agree
    on, rather than duplicated. Relative path; the frontend prefixes it
    with NEXT_PUBLIC_API_BASE, same as every other backend-served image
    URL."""
    path = resolve_template_image_path(template_id)
    if path is None:
        return None
    return f"/static/templates/{path.name}"


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


def _flatten_onto_white(img: Image.Image) -> Image.Image:
    """Returns an RGBA copy with every pixel fully opaque: transparent and
    semi-transparent areas are composited onto white. Every render path
    starts from this, so drawing on top of it never has to care what alpha
    the source had."""
    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    canvas.alpha_composite(img.convert("RGBA"))
    return canvas


def _watermark_layout(size: tuple[int, int], text: str) -> tuple[ImageFont.FreeTypeFont, int, int, int]:
    """Font, outline width and top-left position of the bottom-right
    watermark for an image of `size`. Shared by _draw_watermark and by
    layouts that must keep the watermark's corner clear."""
    img_w, img_h = size
    font_size = max(12, int(img_h * 0.035))
    font = _resolve_font(font_size)
    stroke_width = max(1, font_size // 14)
    padding = max(6, int(img_h * 0.02))
    x = img_w - int(font.getlength(text)) - padding
    y = img_h - font_size - padding
    return font, stroke_width, x, y


def _watermark_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) covering every pixel the watermark can touch,
    outline included."""
    text = get_settings().watermark_text
    font, stroke_width, x, y = _watermark_layout(size, text)
    left, top, right, bottom = font.getbbox(text)
    return (
        x + left - stroke_width - 1,
        y + top - stroke_width - 1,
        x + right + stroke_width + 1,
        y + bottom + stroke_width + 1,
    )


def _draw_watermark(img: Image.Image) -> None:
    """Small brand mark, bottom-right, drawn AFTER captions and independent
    of the TextBoxConfig layout system — it must never reposition or shrink
    a caption box. Solid white fill with a solid black outline, the same
    treatment as the captions. On an RGBA image Pillow writes an ink's
    alpha straight into the pixels rather than blending it, so the ink is
    kept fully opaque to keep the output opaque."""
    settings = get_settings()
    if not settings.watermark_enabled:
        return

    draw = ImageDraw.Draw(img)
    text = settings.watermark_text
    font, stroke_width, x, y = _watermark_layout(img.size, text)

    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))


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


def _compose_gif_frames(
    template_path: Path,
    texts: dict[str, str],
    config,
) -> tuple[list[Image.Image], list[int]]:
    """Growth Phase G. Opens the source animated GIF, caps frame count and
    longest-side dimension up front (predictable render time/output size,
    not a post-hoc retry loop), then reuses _draw_text_in_box/_draw_watermark
    per frame — identical text-layout and brand-mark logic to the static
    path, just run once per frame. Returns (frames, durations_ms); durations
    come from each source frame's own timing so output pacing matches the
    original instead of a guessed fixed value."""
    src = Image.open(template_path)
    frames: list[Image.Image] = []
    durations: list[int] = []

    for i, frame in enumerate(ImageSequence.Iterator(src)):
        if i >= _GIF_MAX_FRAMES:
            break
        duration = frame.info.get("duration", 100) or 100
        rgba = _flatten_onto_white(frame)

        img_w, img_h = rgba.size
        if max(img_w, img_h) > _GIF_MAX_DIMENSION_PX:
            scale = _GIF_MAX_DIMENSION_PX / max(img_w, img_h)
            rgba = rgba.resize((max(1, int(img_w * scale)), max(1, int(img_h * scale))), Image.LANCZOS)
            img_w, img_h = rgba.size

        draw = ImageDraw.Draw(rgba)
        for box_cfg in config.text_boxes:
            text = texts.get(box_cfg.label, "")
            if not text.strip():
                continue
            pixel_box = box_cfg.to_pixels(img_w, img_h)
            _draw_text_in_box(draw, text, box_cfg, pixel_box, img_h)
        _draw_watermark(rgba)

        frames.append(rgba.convert("RGB"))
        durations.append(duration)

    return frames, durations


async def _finalize_and_save_gif(frames: list[Image.Image], durations: list[int]) -> SavedMeme:
    """GIF counterpart to _finalize_and_save — can't share it directly
    since PNG's tEXt provenance chunk and single-frame "format=PNG" save
    have no GIF equivalent. meme_id is embedded as a best-effort GIF
    comment block (same honesty as the PNG tEXt tag: most platforms strip
    metadata on re-encode, the visible watermark — already drawn per-frame
    by _compose_gif_frames — is the durable mark)."""
    meme_id = generate_meme_id()

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        comment=meme_id.encode("ascii"),
    )
    data = buf.getvalue()
    if len(data) > _GIF_MAX_OUTPUT_BYTES:
        print(
            f"[compositor] GIF meme {meme_id} is {len(data) / 1024 / 1024:.1f}MB, "
            f"over the ~{_GIF_MAX_OUTPUT_BYTES / 1024 / 1024:.0f}MB budget — "
            "frame/dimension caps should prevent this; investigate the source template.",
            flush=True,
        )

    return await save_meme(data, meme_id=meme_id, extension="gif", content_type="image/gif")


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

    config = get_config(template_id)

    if config.is_gif:
        frames, durations = _compose_gif_frames(template_path, texts, config)
        return await _finalize_and_save_gif(frames, durations)

    img = _flatten_onto_white(Image.open(template_path))
    img_w, img_h = img.size
    draw = ImageDraw.Draw(img)

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
    img = _flatten_onto_white(image)
    img_w, img_h = img.size

    # The scrims go on their own layer and are composited, so they darken
    # the photo. Drawn straight onto the RGBA image they would replace it
    # with see-through black.
    boxes = []
    scrim = Image.new("RGBA", img.size, (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    for box_cfg in DEFAULT_BOXES:
        text = texts.get(box_cfg.label, "")
        if not text.strip():
            continue
        pixel_box = box_cfg.to_pixels(img_w, img_h)
        x, y, w, h = pixel_box["x"], pixel_box["y"], pixel_box["width"], pixel_box["height"]
        scrim_draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0, 120))
        boxes.append((box_cfg, pixel_box, text))
    img.alpha_composite(scrim)

    draw = ImageDraw.Draw(img)
    for box_cfg, pixel_box, text in boxes:
        _draw_text_in_box(draw, text, box_cfg, pixel_box, img_h)

    return await _finalize_and_save(img)


# --- Arc share card ---
#
# Its own from-scratch rendering path (not a catalog template, not a user's
# own photo). The visual language (violet -> magenta -> pink aura glow
# behind a gradient-filled hero number, a mono-flavored roast readout, a
# tier badge) approximates a hand-designed concept as closely as Pillow's
# toolset allows; it isn't a pixel-exact port of the original mockup —
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


async def compose_arc_card(stats: ArcStats, style: str = "glow") -> SavedMeme:
    """Renders one Arc share card in the requested style. "glow" is the
    original dark card and stays the default. "frontpage" is the white
    tabloid card, rendered only when a request asks for it."""
    if style == "frontpage":
        return await _compose_arc_card_frontpage(stats)
    if style != "glow":
        raise ValueError(f"unknown Arc card style: {style}")
    return await _compose_arc_card_glow(stats)


async def _compose_arc_card_glow(stats: ArcStats) -> SavedMeme:
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

    # Translucent shapes (frame, tier badge, divider) go on their own layer
    # and are composited, so they blend with the card. Drawn straight onto
    # the RGBA card they would leave see-through pixels instead.
    divider_y = int(h * 0.56)
    shapes = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shapes_draw = ImageDraw.Draw(shapes)
    shapes_draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=64, outline=_ARC_VIOLET + (90,), width=3)
    shapes_draw.line([(int(w * 0.08), divider_y), (int(w * 0.92), divider_y)], fill=_ARC_VIOLET + (60,), width=2)

    if stats.tier:
        tier_text = stats.tier.upper()
        tier_font = _resolve_font(int(h * 0.018))
        tier_w = int(tier_font.getlength(tier_text))
        pad_x, pad_y = 22, 14
        badge_x1 = w - int(w * 0.08) - tier_w - pad_x * 2
        badge_y0 = int(h * 0.045)
        shapes_draw.rounded_rectangle(
            [badge_x1, badge_y0, badge_x1 + tier_w + pad_x * 2, badge_y0 + tier_font.size + pad_y],
            radius=999, fill=_ARC_VIOLET + (60,), outline=_ARC_MAGENTA + (140,), width=2,
        )
    img.alpha_composite(shapes)

    draw = ImageDraw.Draw(img)

    # Wordmark + tier badge text
    word_font = _resolve_font(int(h * 0.028))
    draw.text((int(w * 0.08), int(h * 0.05)), "MEMEGPT ARC.", font=word_font, fill=_ARC_TEXT)

    if stats.tier:
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
    draw = ImageDraw.Draw(img)
    draw.text((center_x - label_w // 2, hero_top + text_h + 14), label_text, font=label_font, fill=_ARC_CYAN)

    # Readout lines
    readout_font = _resolve_font(int(h * 0.019))
    lines = [f"{stats.total_memes} memes generated"]
    if stats.top_templates:
        top = stats.top_templates[0]
        lines.append(f"top template: {top.display_name}  {top.roast}")
    if stats.busiest_time_label:
        lines.append(f"busiest: {stats.busiest_time_label}  {stats.hour_roast or ''}".strip())
    lines.append(
        f"chat / lore / make: {stats.chat_count} / {stats.lore_count} / {stats.make_count}"
        f"  {stats.split_roast or ''}".strip()
    )
    lines.append(f"longest streak: {stats.longest_streak_days} days")

    y = divider_y + 20
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


# --- Arc share card, Front Page style ---
#
# White page, near-black type, tabloid red rules and blocks, and the user's
# most-used template shown bare at its true ratio on the shared meme mat.
# Fonts are strict: Anton for display type, Archivo for everything else,
# and no fallback, so a missing font file fails the render instead of
# producing a card in the wrong face.

_FP_WHITE = (255, 255, 255)
_FP_INK = (17, 17, 17)
_FP_RED = (205, 31, 53)
_FP_BLACK = (17, 17, 17)
_FP_MAT = (231, 232, 234)
_FP_EDGE = (191, 193, 196)
_FP_MARGIN = 72
_FP_FOOTER_H = 75

_ARCHIVO_PATH = FONTS_DIR / "Archivo-Variable.ttf"
_ANTON_PATHS = (FONTS_DIR / "Anton-Regular.ttf", Path("/usr/share/fonts/truetype/Anton-Regular.ttf"))


@lru_cache(maxsize=32)
def _archivo(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_ARCHIVO_PATH), size)
    font.set_variation_by_axes([weight, 100])  # axes: weight, width
    return font


@lru_cache(maxsize=32)
def _anton(size: int) -> ImageFont.FreeTypeFont:
    for path in _ANTON_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError("Anton-Regular.ttf is missing from backend/fonts and /usr/share/fonts/truetype")


def _fp_text(draw: ImageDraw.ImageDraw, x: int, top: int, text: str, font, fill) -> int:
    """Draws `text` with its visible top edge at `top` and returns its
    visible bottom edge, so layout spacing is measured between glyphs
    rather than between font bounding boxes."""
    left, t, _, b = font.getbbox(text)
    draw.text((x - left, top - t), text, font=font, fill=fill)
    return top + (b - t)


def _wrap_tokens(tokens: list[str], font, max_width: int) -> list[str]:
    """Greedy line wrap over pre-split tokens. A token is never broken, so
    a phrase that must stay together goes in as one token."""
    lines: list[str] = []
    current = ""
    for token in tokens:
        trial = f"{current} {token}".strip()
        if not current or font.getlength(trial) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def _wrap_to_width(text: str, font, max_width: int) -> list[str]:
    return _wrap_tokens(text.split(), font, max_width)


def _arc_date_span(start: date, end: date) -> str:
    """"SEP 3–NOV 17, 2026", "DEC 20, 2026–FEB 10, 2027" or "NOV 17, 2026"."""

    def month_day(d: date) -> str:
        return f"{d.strftime('%b').upper()} {d.day}"

    if start == end:
        return f"{month_day(end)}, {end.year}"
    if start.year == end.year:
        return f"{month_day(start)}–{month_day(end)}, {end.year}"
    return f"{month_day(start)}, {start.year}–{month_day(end)}, {end.year}"


def _arc_season_line(stats: ArcStats) -> str:
    """"AUTUMN ARC • SEP 3–NOV 17, 2026" when the records fit one season,
    "YOUR ARC • JUN 2–NOV 17, 2026" when they don't. arc/copy.py picks the
    label; the dates are the same span the Arc finale shows."""
    label = (stats.period_label or "Your Arc").upper()
    if not stats.date_span_start or not stats.date_span_end:
        return label
    span = _arc_date_span(date.fromisoformat(stats.date_span_start), date.fromisoformat(stats.date_span_end))
    return f"{label} • {span}"


def _arc_template_image(template_id: str) -> Image.Image | None:
    """The bare catalog template, flattened onto white. An animated
    template contributes its first frame."""
    path = resolve_template_image_path(template_id)
    if path is None:
        return None
    with Image.open(path) as src:
        src.seek(0)
        return _flatten_onto_white(src)


Box = tuple[int, int, int, int]

_FP_LEFT_MIN = 520
_FP_COLUMN_GAP = 48
_FP_COLUMN_MIN_GAIN = 1.5
_FP_MAT_PAD = 14


def _fp_fonts() -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "masthead": _anton(84),
        "season": _archivo(30, 700),
        "score": _anton(196),
        "score_label": _archivo(34, 800),
        "tier": _archivo(34, 800),
        "verdict": _archivo(52, 800),
        "counts": _archivo(32, 600),
        "label": _archivo(30, 700),
        "footer": _archivo(30, 700),
    }


def _ink_size(font, text: str) -> tuple[int, int]:
    left, top, right, bottom = font.getbbox(text)
    return right - left, bottom - top


@dataclass
class _FrontpagePlan:
    """Every position on the Front Page card, worked out before anything is
    drawn. layout is "below" (template under the text), "column" (template
    in a right-hand column level with the score block) or "none"."""

    season_line: str
    season_top: int
    rule_top: int
    score_text: str
    score_block: Box
    score_top: int
    score_label_top: int
    tier_text: str | None
    tier_block: Box | None
    left_width: int
    verdict_lines: list[str]
    verdict_top: int
    counts_text: str
    counts_top: int
    footer_top: int
    footer_bar_right: int
    layout: str
    mat: Box | None
    image_box: Box | None
    label_lines: list[str]
    label_top: int
    area_below: int
    area_column: int


def _counts_line(stats: ArcStats) -> str:
    memes_word = "meme" if stats.total_memes == 1 else "memes"
    templates_word = "template" if stats.distinct_templates == 1 else "different templates"
    return f"{stats.total_memes} {memes_word} • {stats.distinct_templates} {templates_word}"


def _template_label_tokens(display_name: str, count: int) -> list[str]:
    # "• 9 times" is one token so it never splits across lines.
    times = "time" if count == 1 else "times"
    return display_name.split() + [f"• {count} {times}"]


def _fit(template_size: tuple[int, int], avail_w: int, avail_h: int) -> tuple[int, int]:
    tw, th = template_size
    scale = min((avail_w - _FP_MAT_PAD * 2) / tw, (avail_h - _FP_MAT_PAD * 2) / th)
    if scale <= 0:
        return 0, 0
    return max(1, int(tw * scale)), max(1, int(th * scale))


def _frontpage_plan(stats: ArcStats, template_size: tuple[int, int] | None) -> _FrontpagePlan:
    fonts = _fp_fonts()
    w, h = _ARC_CARD_SIZE
    left, right = _FP_MARGIN, w - _FP_MARGIN
    content_w = right - left

    # Masthead, red rule, season line
    _, mast_h = _ink_size(fonts["masthead"], "MemeGPT Arc")
    rule_top = 64 + mast_h + 24
    season_top = rule_top + 7 + 30
    season_line = _arc_season_line(stats)
    _, season_h = _ink_size(fonts["season"], season_line)

    # Score and its label, white inside one solid red block
    score_top = season_top + season_h + 40
    score_text = f"+{stats.aura:,}"
    score_w, score_h = _ink_size(fonts["score"], score_text)
    label_w, label_h = _ink_size(fonts["score_label"], "AURA FARMED")
    pad_x, pad_y, inner_gap = 28, 28, 20
    score_block = (
        left,
        score_top,
        left + max(score_w, label_w) + pad_x * 2,
        score_top + pad_y + score_h + inner_gap + label_h + pad_y,
    )
    y = score_block[3] + 20

    # Tier, white on a solid black block
    tier_text = stats.tier.upper() if stats.tier else None
    tier_block = None
    if tier_text:
        tier_w, tier_h = _ink_size(fonts["tier"], tier_text)
        tier_block = (left, y, left + tier_w + 40, y + tier_h + 28)
        y = tier_block[3] + 40
    text_top = y

    counts_text = _counts_line(stats)
    counts_w, counts_h = _ink_size(fonts["counts"], counts_text)
    left_width = max(
        score_block[2] - left,
        (tier_block[2] - left) if tier_block else 0,
        counts_w,
        _FP_LEFT_MIN,
    )

    def text_column(wrap_width: int) -> tuple[list[str], int, int]:
        """Verdict lines, counts top, and the bottom of the counts line."""
        lines = _wrap_to_width(stats.verdict, fonts["verdict"], wrap_width) if stats.verdict else []
        yy = text_top
        for line in lines:
            yy += _ink_size(fonts["verdict"], line)[1] + 14
        if lines:
            yy += 30 - 14
        return lines, yy, yy + counts_h

    # Footer bar ends before the watermark's corner
    footer_top = h - _FP_FOOTER_H
    footer_bar_right = _watermark_box((w, h))[0] - 28

    _, line_h = _ink_size(fonts["label"], "Ag•")

    def label_block_h(n_lines: int) -> int:
        return n_lines * line_h + (n_lines - 1) * 8

    below_lines, below_counts_top, below_text_bottom = text_column(content_w)
    column_lines, column_counts_top, _ = text_column(left_width)
    top = stats.top_templates[0] if stats.top_templates else None

    plan = _FrontpagePlan(
        season_line=season_line, season_top=season_top, rule_top=rule_top,
        score_text=score_text, score_block=score_block,
        score_top=score_top + pad_y, score_label_top=score_top + pad_y + score_h + inner_gap,
        tier_text=tier_text, tier_block=tier_block, left_width=left_width,
        verdict_lines=below_lines, verdict_top=text_top,
        counts_text=counts_text, counts_top=below_counts_top,
        footer_top=footer_top, footer_bar_right=footer_bar_right,
        layout="none", mat=None, image_box=None, label_lines=[], label_top=0,
        area_below=0, area_column=0,
    )
    if top is None or template_size is None:
        return plan

    tokens = _template_label_tokens(top.display_name, top.count)

    # Below the text, the label on one line under the mat
    below_top = below_text_bottom + 36
    below_label = _wrap_tokens(tokens, fonts["label"], content_w)
    below_size = _fit(
        template_size, content_w, footer_top - 40 - label_block_h(len(below_label)) - 16 - below_top
    )

    # Right-hand column, level with the top of the score block, the label
    # wrapped to the mat's width
    column_x = left + left_width + _FP_COLUMN_GAP
    column_w = right - column_x
    column_label = [""]
    column_size = (0, 0)
    for _ in range(4):
        avail_h = footer_top - 40 - label_block_h(len(column_label)) - 16 - score_block[1]
        column_size = _fit(template_size, column_w, avail_h)
        wrapped = _wrap_tokens(tokens, fonts["label"], column_size[0] + _FP_MAT_PAD * 2)
        if len(wrapped) <= len(column_label):
            column_label = wrapped
            break
        column_label = wrapped

    plan.area_below = below_size[0] * below_size[1]
    plan.area_column = column_size[0] * column_size[1]

    if plan.area_column >= _FP_COLUMN_MIN_GAIN * plan.area_below and plan.area_column > 0:
        plan.layout = "column"
        plan.verdict_lines, plan.counts_top = column_lines, column_counts_top
        mat_x, mat_y, (iw, ih), plan.label_lines = column_x, score_block[1], column_size, column_label
    elif plan.area_below > 0:
        plan.layout = "below"
        mat_x, mat_y, (iw, ih), plan.label_lines = left, below_top, below_size, below_label
    else:
        return plan

    plan.mat = (mat_x, mat_y, mat_x + iw + _FP_MAT_PAD * 2, mat_y + ih + _FP_MAT_PAD * 2)
    plan.image_box = (mat_x + _FP_MAT_PAD, mat_y + _FP_MAT_PAD, mat_x + _FP_MAT_PAD + iw, mat_y + _FP_MAT_PAD + ih)
    plan.label_top = plan.mat[3] + 16
    return plan


async def _compose_arc_card_frontpage(stats: ArcStats) -> SavedMeme:
    w, h = _ARC_CARD_SIZE
    left, right = _FP_MARGIN, w - _FP_MARGIN
    fonts = _fp_fonts()

    top = stats.top_templates[0] if stats.top_templates else None
    template = _arc_template_image(top.template_id) if top else None
    plan = _frontpage_plan(stats, template.size if template is not None else None)

    img = Image.new("RGBA", (w, h), _FP_WHITE + (255,))
    draw = ImageDraw.Draw(img)

    _fp_text(draw, left, 64, "MemeGPT Arc", fonts["masthead"], _FP_INK)
    draw.rectangle([left, plan.rule_top, right, plan.rule_top + 7], fill=_FP_RED)
    _fp_text(draw, left, plan.season_top, plan.season_line, fonts["season"], _FP_INK)

    draw.rectangle(plan.score_block, fill=_FP_RED)
    _fp_text(draw, left + 28, plan.score_top, plan.score_text, fonts["score"], _FP_WHITE)
    _fp_text(draw, left + 28, plan.score_label_top, "AURA FARMED", fonts["score_label"], _FP_WHITE)

    if plan.tier_block and plan.tier_text:
        draw.rectangle(plan.tier_block, fill=_FP_BLACK)
        _fp_text(draw, left + 20, plan.tier_block[1] + 14, plan.tier_text, fonts["tier"], _FP_WHITE)

    y = plan.verdict_top
    for line in plan.verdict_lines:
        y = _fp_text(draw, left, y, line, fonts["verdict"], _FP_INK) + 14
    _fp_text(draw, left, plan.counts_top, plan.counts_text, fonts["counts"], _FP_INK)

    draw.rectangle([0, plan.footer_top, plan.footer_bar_right, h], fill=_FP_RED)
    _, foot_h = _ink_size(fonts["footer"], "memegpt.app/arc")
    _fp_text(draw, left, plan.footer_top + (_FP_FOOTER_H - foot_h) // 2, "memegpt.app/arc", fonts["footer"], _FP_WHITE)

    if template is not None and plan.mat and plan.image_box:
        x0, y0, x1, y1 = plan.image_box
        draw.rectangle(plan.mat, fill=_FP_MAT, outline=_FP_EDGE, width=1)
        img.paste(template.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
        draw.rectangle([x0 - 1, y0 - 1, x1, y1], outline=_FP_EDGE, width=1)
        _, line_h = _ink_size(fonts["label"], "Ag•")
        ly = plan.label_top
        for line in plan.label_lines:
            _fp_text(draw, plan.mat[0], ly, line, fonts["label"], _FP_INK)
            ly += line_h + 8

    return await _finalize_and_save(img)
