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
# Per-template configs — multi-panel or non-standard layouts
# ---------------------------------------------------------------------------
TEMPLATE_CATALOG: dict[str, TemplateConfig] = {

    # ── Drake Hotline Bling ──────────────────────────────────────────────────
    # 2×2 grid: left column = Drake's face, right column = text
    "drake": TemplateConfig(
        template_id="drake",
        text_boxes=[
            TextBoxConfig("rejected_option", x_pct=51, y_pct=3,  w_pct=46, h_pct=43, font_size_pct=5.5),
            TextBoxConfig("approved_option", x_pct=51, y_pct=53, w_pct=46, h_pct=43, font_size_pct=5.5),
        ],
        box_descriptions={
            "rejected_option": "The thing being rejected/disliked (top panel)",
            "approved_option": "The thing being preferred/approved (bottom panel — the punchline)",
        },
    ),

    # ── Distracted Boyfriend ────────────────────────────────────────────────
    # Landscape: other_woman walks in from left, boyfriend center turns to look,
    # girlfriend right looks upset. Labels placed near each person's body.
    "distracted_boyfriend": TemplateConfig(
        template_id="distracted_boyfriend",
        text_boxes=[
            TextBoxConfig("other_woman", x_pct=2,  y_pct=65, w_pct=30, h_pct=28, font_size_pct=5),
            TextBoxConfig("boyfriend",   x_pct=30, y_pct=4,  w_pct=38, h_pct=20, font_size_pct=5),
            TextBoxConfig("girlfriend",  x_pct=62, y_pct=4,  w_pct=36, h_pct=20, font_size_pct=5),
        ],
        box_descriptions={
            "other_woman": "The tempting new thing the person is distracted by (left, red dress)",
            "boyfriend":   "The person doing the ignoring — often 'me' or the user (center)",
            "girlfriend":  "The thing being neglected/abandoned (right)",
        },
    ),

    # ── Gru's Plan ──────────────────────────────────────────────────────────
    # 2×2 panels; text overlays top portion of each quadrant
    "grus_plan": TemplateConfig(
        template_id="grus_plan",
        text_boxes=[
            TextBoxConfig("step_1", x_pct=2,  y_pct=3,  w_pct=46, h_pct=30, font_size_pct=5),
            TextBoxConfig("step_2", x_pct=52, y_pct=3,  w_pct=46, h_pct=30, font_size_pct=5),
            TextBoxConfig("step_3", x_pct=2,  y_pct=53, w_pct=46, h_pct=30, font_size_pct=5),
            TextBoxConfig("step_4", x_pct=52, y_pct=53, w_pct=46, h_pct=30, font_size_pct=5),
        ],
        box_descriptions={
            "step_1": "First step of the plan (top-left panel)",
            "step_2": "Second step (top-right panel)",
            "step_3": "Third step — this is where it goes wrong (bottom-left panel)",
            "step_4": "Fourth step — same as step 2 but Gru is horrified (bottom-right). Mirror step 2 to reveal the flaw.",
        },
    ),

    # ── Woman Yelling at Cat ─────────────────────────────────────────────────
    "woman_yelling_at_cat": TemplateConfig(
        template_id="woman_yelling_at_cat",
        text_boxes=[
            TextBoxConfig("yelling_woman", x_pct=2,  y_pct=65, w_pct=46, h_pct=32, font_size_pct=5),
            TextBoxConfig("confused_cat",  x_pct=52, y_pct=65, w_pct=46, h_pct=32, font_size_pct=5),
        ],
        box_descriptions={
            "yelling_woman": "What the person is angrily insisting/demanding (left panel)",
            "confused_cat":  "The calm, unbothered response or reality (right panel — the cat)",
        },
    ),

    # ── Expanding Brain ──────────────────────────────────────────────────────
    # 4 rows; LEFT half = white text area, RIGHT half = brain image
    "expanding_brain": TemplateConfig(
        template_id="expanding_brain",
        text_boxes=[
            TextBoxConfig("level_1", x_pct=2, y_pct=2,  w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("level_2", x_pct=2, y_pct=26, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("level_3", x_pct=2, y_pct=51, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("level_4", x_pct=2, y_pct=76, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
        ],
        box_descriptions={
            "level_1": "The basic/dumb take (small brain)",
            "level_2": "Slightly smarter take",
            "level_3": "Big brain take",
            "level_4": "Galaxy brain / absurdly enlightened take (biggest brain)",
        },
    ),

    # ── Galaxy Brain ─────────────────────────────────────────────────────────
    # Same 4-row layout as Expanding Brain (LEFT half = white text, RIGHT = brain)
    "galaxy_brain": TemplateConfig(
        template_id="galaxy_brain",
        text_boxes=[
            TextBoxConfig("logic_1", x_pct=2, y_pct=2,  w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("logic_2", x_pct=2, y_pct=26, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("logic_3", x_pct=2, y_pct=51, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
            TextBoxConfig("logic_4", x_pct=2, y_pct=76, w_pct=46, h_pct=21, font_size_pct=4.5, font_color="#000000", stroke_color="#CCCCCC"),
        ],
        box_descriptions={
            "logic_1": "The starting premise (reasonable)",
            "logic_2": "The reasoning gets a bit stretched",
            "logic_3": "Now it's getting absurd",
            "logic_4": "The wild galaxy-brained conclusion everyone arrives at",
        },
    ),

    # ── Two Buttons ──────────────────────────────────────────────────────────
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

    # ── Always Has Been ──────────────────────────────────────────────────────
    "always_has_been": TemplateConfig(
        template_id="always_has_been",
        text_boxes=[
            TextBoxConfig("realization",   x_pct=3,  y_pct=5,  w_pct=55, h_pct=30, font_size_pct=5.5),
            TextBoxConfig("always_has_been", x_pct=48, y_pct=58, w_pct=50, h_pct=35, font_size_pct=5),
        ],
        box_descriptions={
            "realization":    "The surprising realization — 'Wait, [X] was always [Y]?'",
            "always_has_been": "The dark confirmation — 'Always has been.' (with gun pointed)",
        },
    ),

    # ── Batman Slapping Robin ────────────────────────────────────────────────
    "batman_slapping_robin": TemplateConfig(
        template_id="batman_slapping_robin",
        text_boxes=[
            TextBoxConfig("robin_says",  x_pct=3,  y_pct=3,  w_pct=55, h_pct=40, font_size_pct=5.5),
            TextBoxConfig("batman_slap", x_pct=50, y_pct=48, w_pct=47, h_pct=45, font_size_pct=5.5),
        ],
        box_descriptions={
            "robin_says":  "What Robin (the wrong one) says — the naive or incorrect take",
            "batman_slap": "Batman's correction — what shuts the wrong take down",
        },
    ),

    # ── Buff Doge vs Cheems ──────────────────────────────────────────────────
    "buff_doge_vs_cheems": TemplateConfig(
        template_id="buff_doge_vs_cheems",
        text_boxes=[
            TextBoxConfig("buff_doge", x_pct=2,  y_pct=2, w_pct=44, h_pct=25, font_size_pct=5),
            TextBoxConfig("cheems",    x_pct=54, y_pct=2, w_pct=44, h_pct=25, font_size_pct=5),
        ],
        box_descriptions={
            "buff_doge": "The strong/idealized past or better version (left)",
            "cheems":    "The weak/sad present or lesser version (right)",
        },
    ),

    # ── Surprised Pikachu ────────────────────────────────────────────────────
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

    # ── Left Exit 12 Off Ramp ────────────────────────────────────────────────
    # Highway scene: car swerving to take exit
    "left_exit_12": TemplateConfig(
        template_id="left_exit_12",
        text_boxes=[
            TextBoxConfig("car",         x_pct=62, y_pct=5,  w_pct=36, h_pct=22, font_size_pct=4.5),
            TextBoxConfig("straight",    x_pct=62, y_pct=48, w_pct=36, h_pct=22, font_size_pct=4.5),
            TextBoxConfig("exit",        x_pct=5,  y_pct=65, w_pct=45, h_pct=28, font_size_pct=4.5),
        ],
        box_descriptions={
            "car":      "Who or what is swerving/making the choice (the driver)",
            "straight": "The sensible planned path being abandoned (the highway going straight)",
            "exit":     "The tempting thing being swerved toward (the exit ramp)",
        },
    ),

    # ── Change My Mind ───────────────────────────────────────────────────────
    # Man at table with a sign/board — text goes in the blank whitespace ABOVE "CHANGE MY MIND"
    "change_my_mind": TemplateConfig(
        template_id="change_my_mind",
        text_boxes=[
            TextBoxConfig("opinion", x_pct=24, y_pct=52, w_pct=52, h_pct=26, font_size_pct=5, uppercase=False),
        ],
        box_descriptions={
            "opinion": "The bold or controversial opinion written on the table sign — just state the opinion, don't add 'change my mind'",
        },
    ),

    # ── Anakin Padmé (4-panel Star Wars) ────────────────────────────────────
    # 2×2: top-left=Anakin statement, top-right=Padme assumption, bottom-left=Anakin silent, bottom-right=Padme worried
    "anakin_padme": TemplateConfig(
        template_id="anakin_padme",
        text_boxes=[
            TextBoxConfig("anakin_says",   x_pct=3,  y_pct=3,  w_pct=44, h_pct=16, font_size_pct=3.8, uppercase=False),
            TextBoxConfig("padme_assumes", x_pct=53, y_pct=3,  w_pct=44, h_pct=16, font_size_pct=3.8, uppercase=False),
            TextBoxConfig("anakin_silent", x_pct=3,  y_pct=53, w_pct=44, h_pct=16, font_size_pct=3.8, uppercase=False),
            TextBoxConfig("padme_nervous", x_pct=53, y_pct=53, w_pct=44, h_pct=16, font_size_pct=3.8, uppercase=False),
        ],
        box_descriptions={
            "anakin_says":   "What Anakin declares or announces (top-left — sets up the scenario)",
            "padme_assumes": "What Padme hopefully assumes will follow — 'So we'll do X, right?' (top-right)",
            "anakin_silent": "Anakin says nothing — leave this blank or use '...' (bottom-left)",
            "padme_nervous": "Padme's nervous repeat — 'right?' (bottom-right, the punchline)",
        },
    ),

    # ── This Is Fine ─────────────────────────────────────────────────────────
    # 2-panel landscape: left = dog sitting in fire, right = dog close-up
    # "THIS IS FINE" is already baked into the image — only add situation context
    "this_is_fine": TemplateConfig(
        template_id="this_is_fine",
        text_boxes=[
            TextBoxConfig("situation", x_pct=2, y_pct=3, w_pct=46, h_pct=30, font_size_pct=6),
        ],
        box_descriptions={
            "situation": "The chaotic situation being ignored — describes what's on fire (top of left panel). Do NOT add 'this is fine' text; it is already in the image.",
        },
    ),

    # ── Hide the Pain Harold ─────────────────────────────────────────────────
    # 2-panel portrait stacked: top = Harold neutral, bottom = Harold pained smile
    # Text goes BELOW Harold's face in each panel (chest/body area), not over his head
    "hide_the_pain_harold": TemplateConfig(
        template_id="hide_the_pain_harold",
        text_boxes=[
            TextBoxConfig("public_face",  x_pct=5, y_pct=33, w_pct=90, h_pct=13, font_size_pct=5.5),
            TextBoxConfig("inner_reality", x_pct=5, y_pct=80, w_pct=90, h_pct=16, font_size_pct=5.5),
        ],
        box_descriptions={
            "public_face":   "What Harold is outwardly presenting or pretending — the false front (lower part of top panel)",
            "inner_reality": "The painful truth he's hiding behind that smile (lower part of bottom panel)",
        },
    ),

    # ── Boardroom Meeting Suggestion ─────────────────────────────────────────
    # 3-panel vertical: presenter pitches idea → 3 employees all suggest same thing → boss throws them out
    "boardroom_meeting_suggestion": TemplateConfig(
        template_id="boardroom_meeting_suggestion",
        text_boxes=[
            TextBoxConfig("suggestion",  x_pct=12, y_pct=1,  w_pct=41, h_pct=14, font_size_pct=4,   uppercase=False),
            TextBoxConfig("person_1",    x_pct=4,  y_pct=33, w_pct=22, h_pct=10, font_size_pct=3.5, uppercase=False),
            TextBoxConfig("person_2",    x_pct=28, y_pct=32, w_pct=24, h_pct=9,  font_size_pct=3.5, uppercase=False),
            TextBoxConfig("person_3",    x_pct=53, y_pct=31, w_pct=43, h_pct=14, font_size_pct=3.5, uppercase=False),
            TextBoxConfig("reaction",    x_pct=5,  y_pct=83, w_pct=90, h_pct=13, font_size_pct=4.5),
        ],
        box_descriptions={
            "suggestion": "The idea being pitched by the presenter (panel 1 speech bubble)",
            "person_1":   "Left employee's take — a slight variation of the same idea (panel 2, left bubble)",
            "person_2":   "Center employee's take (panel 2, center bubble)",
            "person_3":   "Right employee's take — often the dumbest or most obvious (panel 2, right bubble)",
            "reaction":   "What the boss does in response — usually throws them out (panel 3 caption)",
        },
    ),

    # ── Doge ─────────────────────────────────────────────────────────────────
    # Scattered Comic-Sans style text around a Shiba Inu — 5 position zones
    "doge": TemplateConfig(
        template_id="doge",
        text_boxes=[
            TextBoxConfig("wow",    x_pct=2,  y_pct=2,  w_pct=38, h_pct=14, font_size_pct=6, font_color="#FF69B4", uppercase=False),
            TextBoxConfig("such",   x_pct=60, y_pct=5,  w_pct=38, h_pct=14, font_size_pct=6, font_color="#FFD700", uppercase=False),
            TextBoxConfig("very",   x_pct=2,  y_pct=40, w_pct=35, h_pct=14, font_size_pct=6, font_color="#00BFFF", uppercase=False),
            TextBoxConfig("much",   x_pct=63, y_pct=38, w_pct=35, h_pct=14, font_size_pct=6, font_color="#7CFC00", uppercase=False),
            TextBoxConfig("many",   x_pct=15, y_pct=72, w_pct=70, h_pct=18, font_size_pct=6, font_color="#FF6347", uppercase=False),
        ],
        box_descriptions={
            "wow":  "Top-left — 'wow' phrase (e.g. 'wow such code')",
            "such": "Top-right — 'such' phrase (e.g. 'such amaze')",
            "very": "Middle-left — 'very' phrase (e.g. 'very confused')",
            "much": "Middle-right — 'much' phrase (e.g. 'much wow')",
            "many": "Bottom-center — final phrase (e.g. 'many meme, very format')",
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
