"""
Per-template text box definitions and LLM prompt metadata.

Each TemplateConfig defines:
  - Where text boxes sit (as percentages of image dimensions, so they work
    regardless of the downloaded image resolution)
  - What each box means, so the LLM prompt can explain them to the model

Coordinates (x_pct, y_pct, w_pct, h_pct) are percentages of image
width/height. The compositor converts them to pixels at render time.

Templates not in TEMPLATE_CATALOG fall back to DEFAULT_BOXES.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBoxConfig:
    label: str
    x_pct: float        # left edge, % of image width
    y_pct: float        # top edge, % of image height
    w_pct: float        # box width, % of image width
    h_pct: float        # box height, % of image height
    font_size_pct: float = 7.0   # font size as % of image height
    font_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    uppercase: bool = True

    def to_pixels(self, img_w: int, img_h: int) -> dict[str, int]:
        return {
            "x": int(img_w * self.x_pct / 100),
            "y": int(img_h * self.y_pct / 100),
            "width": int(img_w * self.w_pct / 100),
            "height": int(img_h * self.h_pct / 100),
        }

    def font_size_px(self, img_h: int) -> int:
        return max(16, int(img_h * self.font_size_pct / 100))


@dataclass
class TemplateConfig:
    template_id: str
    text_boxes: list[TextBoxConfig]
    # Human-readable description of each box — injected into LLM system prompt
    box_descriptions: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Default layout — top and bottom caption zones (classic meme style)
# ---------------------------------------------------------------------------
DEFAULT_BOXES = [
    TextBoxConfig("top_text",    x_pct=5,  y_pct=2,  w_pct=90, h_pct=20, font_size_pct=7),
    TextBoxConfig("bottom_text", x_pct=5,  y_pct=78, w_pct=90, h_pct=20, font_size_pct=7),
]

DEFAULT_BOX_DESCRIPTIONS = {
    "top_text":    "Caption at the top of the meme",
    "bottom_text": "Caption at the bottom of the meme (punchline goes here)",
}

# ---------------------------------------------------------------------------
# Per-template configs
# ---------------------------------------------------------------------------
TEMPLATE_CATALOG: dict[str, TemplateConfig] = {

    # Drake Hotline Bling
    # 2×2 grid: left column = Drake's face, right column = text
    # Top row = rejection, Bottom row = approval
    "drake": TemplateConfig(
        template_id="drake",
        text_boxes=[
            TextBoxConfig("rejected_option", x_pct=51, y_pct=3,  w_pct=46, h_pct=43, font_size_pct=5.5),
            TextBoxConfig("approved_option", x_pct=51, y_pct=53, w_pct=46, h_pct=43, font_size_pct=5.5),
        ],
        box_descriptions={
            "rejected_option": "The thing being rejected/disliked (top panel)",
            "approved_option": "The thing being preferred/approved (bottom panel — this is the punchline)",
        },
    ),

    # Distracted Boyfriend
    # Landscape: other woman (left, red dress), boyfriend (center), girlfriend (right)
    "distracted_boyfriend": TemplateConfig(
        template_id="distracted_boyfriend",
        text_boxes=[
            TextBoxConfig("other_woman", x_pct=2,  y_pct=2, w_pct=28, h_pct=16, font_size_pct=4.5, uppercase=False),
            TextBoxConfig("boyfriend",   x_pct=32, y_pct=2, w_pct=34, h_pct=16, font_size_pct=4.5, uppercase=False),
            TextBoxConfig("girlfriend",  x_pct=68, y_pct=2, w_pct=30, h_pct=16, font_size_pct=4.5, uppercase=False),
        ],
        box_descriptions={
            "other_woman": "The tempting new thing the person is distracted by (left, in red dress)",
            "boyfriend":   "The person/subject doing the ignoring — often 'me' or the user (center)",
            "girlfriend":  "The thing being neglected/abandoned (right)",
        },
    ),

    # Gru's Plan — 2×2 panels; text overlays top portion of each quadrant
    "grus_plan": TemplateConfig(
        template_id="grus_plan",
        text_boxes=[
            TextBoxConfig("step_1", x_pct=2,  y_pct=2,  w_pct=46, h_pct=20, font_size_pct=4),
            TextBoxConfig("step_2", x_pct=52, y_pct=2,  w_pct=46, h_pct=20, font_size_pct=4),
            TextBoxConfig("step_3", x_pct=2,  y_pct=52, w_pct=46, h_pct=20, font_size_pct=4),
            TextBoxConfig("step_4", x_pct=52, y_pct=52, w_pct=46, h_pct=20, font_size_pct=4),
        ],
        box_descriptions={
            "step_1": "First step of the plan (top-left panel)",
            "step_2": "Second step (top-right panel)",
            "step_3": "Third step — this is where it goes wrong (bottom-left panel)",
            "step_4": "Fourth step — same as step 2 but Gru is horrified (bottom-right panel). Should mirror or repeat step 2 to reveal the flaw.",
        },
    ),

    # Woman Yelling at Cat — two panels side by side
    "woman_yelling_at_cat": TemplateConfig(
        template_id="woman_yelling_at_cat",
        text_boxes=[
            TextBoxConfig("yelling_woman", x_pct=2,  y_pct=65, w_pct=46, h_pct=32, font_size_pct=5),
            TextBoxConfig("confused_cat",  x_pct=52, y_pct=65, w_pct=46, h_pct=32, font_size_pct=5),
        ],
        box_descriptions={
            "yelling_woman": "What the person/group is angrily insisting or demanding (left panel)",
            "confused_cat":  "The calm, unbothered response or reality (right panel — the cat)",
        },
    ),

    # Expanding Brain — 4 rows; text in right half of each row
    "expanding_brain": TemplateConfig(
        template_id="expanding_brain",
        text_boxes=[
            TextBoxConfig("level_1", x_pct=50, y_pct=2,  w_pct=48, h_pct=21, font_size_pct=4.5),
            TextBoxConfig("level_2", x_pct=50, y_pct=26, w_pct=48, h_pct=21, font_size_pct=4.5),
            TextBoxConfig("level_3", x_pct=50, y_pct=51, w_pct=48, h_pct=21, font_size_pct=4.5),
            TextBoxConfig("level_4", x_pct=50, y_pct=76, w_pct=48, h_pct=21, font_size_pct=4.5),
        ],
        box_descriptions={
            "level_1": "The basic/dumb take (small brain)",
            "level_2": "Slightly smarter take",
            "level_3": "Big brain take",
            "level_4": "Galaxy brain / absurdly enlightened take (biggest brain)",
        },
    ),

    # Two Buttons — text labels on the two buttons and nervous person
    "two_buttons": TemplateConfig(
        template_id="two_buttons",
        text_boxes=[
            TextBoxConfig("button_1", x_pct=3,  y_pct=3,  w_pct=38, h_pct=28, font_size_pct=5),
            TextBoxConfig("button_2", x_pct=55, y_pct=3,  w_pct=38, h_pct=28, font_size_pct=5),
        ],
        box_descriptions={
            "button_1": "First difficult option — both buttons are equally tempting or bad",
            "button_2": "Second difficult option",
        },
    ),

    # Always Has Been
    "always_has_been": TemplateConfig(
        template_id="always_has_been",
        text_boxes=[
            TextBoxConfig("realization", x_pct=3,  y_pct=5,  w_pct=55, h_pct=30, font_size_pct=5.5),
            TextBoxConfig("always_has_been", x_pct=48, y_pct=58, w_pct=50, h_pct=35, font_size_pct=5),
        ],
        box_descriptions={
            "realization": "The surprising realization — 'Wait, [X] was always [Y]?'",
            "always_has_been": "The dark confirmation — 'Always has been.' (with gun pointed)",
        },
    ),

    # Batman Slapping Robin
    "batman_slapping_robin": TemplateConfig(
        template_id="batman_slapping_robin",
        text_boxes=[
            TextBoxConfig("robin_says",  x_pct=3,  y_pct=3,  w_pct=55, h_pct=40, font_size_pct=5.5),
            TextBoxConfig("batman_slap", x_pct=50, y_pct=48, w_pct=47, h_pct=45, font_size_pct=5.5),
        ],
        box_descriptions={
            "robin_says":  "What Robin (the person being corrected) says — the wrong/naive take",
            "batman_slap": "Batman's correction — what shuts down the wrong take",
        },
    ),

    # Buff Doge vs Cheems
    "buff_doge_vs_cheems": TemplateConfig(
        template_id="buff_doge_vs_cheems",
        text_boxes=[
            TextBoxConfig("buff_doge",  x_pct=2,  y_pct=2, w_pct=44, h_pct=25, font_size_pct=5),
            TextBoxConfig("cheems",     x_pct=54, y_pct=2, w_pct=44, h_pct=25, font_size_pct=5),
        ],
        box_descriptions={
            "buff_doge":  "The strong/idealized past or better version (left)",
            "cheems":     "The weak/sad present or lesser version (right)",
        },
    ),

    # Surprised Pikachu — simple bottom caption
    "surprised_pikachu": TemplateConfig(
        template_id="surprised_pikachu",
        text_boxes=[
            TextBoxConfig("setup",    x_pct=5, y_pct=2,  w_pct=90, h_pct=18, font_size_pct=6),
            TextBoxConfig("reaction", x_pct=5, y_pct=75, w_pct=90, h_pct=22, font_size_pct=6),
        ],
        box_descriptions={
            "setup":    "The action taken that led to an obvious consequence",
            "reaction": "The shocked reaction — Pikachu's face IS the punchline",
        },
    ),
}


def get_config(template_id: str) -> TemplateConfig:
    """Return the TemplateConfig for a template, falling back to default top/bottom layout."""
    if template_id in TEMPLATE_CATALOG:
        return TEMPLATE_CATALOG[template_id]
    return TemplateConfig(
        template_id=template_id,
        text_boxes=DEFAULT_BOXES,
        box_descriptions=DEFAULT_BOX_DESCRIPTIONS,
    )


