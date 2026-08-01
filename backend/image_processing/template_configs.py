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
    # Growth Phase G — animated GIF templates. compositor.py's compose_meme()
    # branches on this right after resolving the template's source file;
    # everything else about a gif TemplateConfig (text_boxes, box_descriptions)
    # works identically to a static one.
    is_gif: bool = False


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
            "step_4": "Fourth step — repeat step 3 EXACTLY, Gru is horrified realizing the flaw (bottom-right panel).",
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
    # 3-panel vertical (500x649): presenter pitches → 3 employees echo → boss throws someone out
    # Increased font sizes — speech bubbles are small areas, need larger text to be readable
    "boardroom_meeting_suggestion": TemplateConfig(
        template_id="boardroom_meeting_suggestion",
        text_boxes=[
            TextBoxConfig("suggestion",  x_pct=12, y_pct=1,  w_pct=41, h_pct=14, font_size_pct=5,   uppercase=False),
            TextBoxConfig("person_1",    x_pct=4,  y_pct=33, w_pct=22, h_pct=10, font_size_pct=5,   uppercase=False),
            TextBoxConfig("person_2",    x_pct=28, y_pct=32, w_pct=24, h_pct=9,  font_size_pct=5,   uppercase=False),
            TextBoxConfig("person_3",    x_pct=53, y_pct=31, w_pct=43, h_pct=14, font_size_pct=5,   uppercase=False),
            TextBoxConfig("reaction",    x_pct=5,  y_pct=83, w_pct=90, h_pct=13, font_size_pct=5.5),
        ],
        box_descriptions={
            "suggestion": "The idea being pitched by the presenter (panel 1 speech bubble)",
            "person_1":   "Left employee's take — a slight variation of the same bad idea (panel 2, left bubble)",
            "person_2":   "Center employee's take (panel 2, center bubble)",
            "person_3":   "Right employee's take — often the dumbest or most obvious (panel 2, right bubble)",
            "reaction":   "What the boss does — usually throws them all out (panel 3 caption)",
        },
    ),

    # ── Evil Kermit ──────────────────────────────────────────────────────────
    # 700x325 landscape — two-panel side-by-side: LEFT = regular Kermit, RIGHT = hooded evil Kermit.
    # Text at the bottom of each half so it doesn't cover the faces.
    "evil_kermit": TemplateConfig(
        template_id="evil_kermit",
        text_boxes=[
            TextBoxConfig("regular_kermit", x_pct=2,  y_pct=62, w_pct=46, h_pct=35, font_size_pct=6.5, uppercase=False),
            TextBoxConfig("evil_kermit",    x_pct=52, y_pct=62, w_pct=46, h_pct=35, font_size_pct=6.5, uppercase=False),
        ],
        box_descriptions={
            "regular_kermit": "The responsible, sensible thought — what you SHOULD do (left panel, regular Kermit)",
            "evil_kermit":    "The dark temptation — what your inner demon is actually suggesting (right panel, hooded evil Kermit)",
        },
    ),

    # ── Drunk Friend Caught on Camera ────────────────────────────────────────
    # Portrait phone video with large black bars top and bottom — face in middle.
    # Text goes in the black bars where it's always legible.
    "drunk_friend_caught": TemplateConfig(
        template_id="drunk_friend_caught",
        text_boxes=[
            TextBoxConfig("top_text",    x_pct=4, y_pct=4,  w_pct=92, h_pct=26, font_size_pct=7),
            TextBoxConfig("bottom_text", x_pct=4, y_pct=82, w_pct=92, h_pct=14, font_size_pct=6),
        ],
        box_descriptions={
            "top_text":    "The setup — what situation or feeling led to this moment",
            "bottom_text": "The punchline — his dazed reaction or what he's thinking",
        },
    ),

    # ── Indian Templates ─────────────────────────────────────────────────────

    # Baburao (640x640 square) — bottom ~15% has a baked-in subtitle strip;
    # keep both text boxes above y=72 so captions never overlap the subtitle.
    "baburao": TemplateConfig(
        template_id="baburao",
        text_boxes=[
            TextBoxConfig("top_text",    x_pct=5, y_pct=2,  w_pct=90, h_pct=22, font_size_pct=7),
            TextBoxConfig("bottom_text", x_pct=5, y_pct=54, w_pct=90, h_pct=22, font_size_pct=7),
        ],
        box_descriptions={
            "top_text":    "The problem or situation that needs solving",
            "bottom_text": "Baburao's absurd, wrong, or confidently delivered solution",
        },
    ),

    # SRK DDLJ train scene (600x450) — landscape, two people reaching for each other;
    # top text over sky, bottom text over ground/crowd area
    "srk_ddlj": TemplateConfig(
        template_id="srk_ddlj",
        text_boxes=[
            TextBoxConfig("top_text",    x_pct=5, y_pct=2,  w_pct=90, h_pct=20, font_size_pct=7),
            TextBoxConfig("bottom_text", x_pct=5, y_pct=78, w_pct=90, h_pct=20, font_size_pct=6),
        ],
        box_descriptions={
            "top_text":    "What was almost missed / the setup for the last-minute moment",
            "bottom_text": "The barely-made-it punchline or dramatic declaration",
        },
    ),

    # Circuit (400x712 portrait) — tall image, face in centre; push text to clear edges
    "circuit_plan": TemplateConfig(
        template_id="circuit_plan",
        text_boxes=[
            TextBoxConfig("top_text",    x_pct=5, y_pct=2,  w_pct=90, h_pct=16, font_size_pct=6),
            TextBoxConfig("bottom_text", x_pct=5, y_pct=82, w_pct=90, h_pct=16, font_size_pct=6),
        ],
        box_descriptions={
            "top_text":    "The problem or situation Circuit is scheming about",
            "bottom_text": "His confident jugaad plan (probably terrible, definitely stated with conviction)",
        },
    ),

    # Jethalal 4-panel (645x476) — 2×2 grid of escalating shock expressions;
    # single top caption for setup, single bottom for peak-panic punchline
    "jethalal_panic": TemplateConfig(
        template_id="jethalal_panic",
        text_boxes=[
            TextBoxConfig("top_text",    x_pct=5, y_pct=2,  w_pct=90, h_pct=18, font_size_pct=6),
            TextBoxConfig("bottom_text", x_pct=5, y_pct=80, w_pct=90, h_pct=18, font_size_pct=6),
        ],
        box_descriptions={
            "top_text":    "What Jethalal just found out / what triggered the escalating panic",
            "bottom_text": "Peak horror — the worst-case realisation (the final panel energy)",
        },
    ),

    # Mogambo (400x274 landscape) — villain in costume, dark tones; classic top/bottom
    "mogambo_khush": TemplateConfig(
        template_id="mogambo_khush",
        text_boxes=[
            TextBoxConfig("evil_plan",      x_pct=5, y_pct=2,  w_pct=90, h_pct=28, font_size_pct=7),
            TextBoxConfig("mogambo_khush",  x_pct=5, y_pct=68, w_pct=90, h_pct=28, font_size_pct=7),
        ],
        box_descriptions={
            "evil_plan":    "What worked out / the plan that succeeded or karma that landed",
            "mogambo_khush": "The villainous satisfaction — 'Mogambo khush hua'",
        },
    ),

    # Gabbar (640x480) — outdoor scene with revolver; interrogation format
    "sholay_gabbar": TemplateConfig(
        template_id="sholay_gabbar",
        text_boxes=[
            TextBoxConfig("question",  x_pct=5, y_pct=2,  w_pct=90, h_pct=22, font_size_pct=6, uppercase=False),
            TextBoxConfig("failure",   x_pct=5, y_pct=76, w_pct=90, h_pct=22, font_size_pct=7),
        ],
        box_descriptions={
            "question": "Gabbar's demand — 'Kitne aadmi the?' / what task was given",
            "failure":  "The embarrassing failure / what went wrong",
        },
    ),

    # ── Mr. Incredible Uncanny (2-panel horror, 1157x651) ────────────────────
    # LEFT panel = dark uncanny/traumatized version, RIGHT panel = normal Mr. Incredible
    "mr_incredible_uncanny": TemplateConfig(
        template_id="mr_incredible_uncanny",
        text_boxes=[
            TextBoxConfig("before", x_pct=52, y_pct=3, w_pct=46, h_pct=22, font_size_pct=5.5),
            TextBoxConfig("after",  x_pct=2,  y_pct=3, w_pct=46, h_pct=22, font_size_pct=5.5),
        ],
        box_descriptions={
            "before": "The blissfully ignorant state — what you knew/believed BEFORE (RIGHT panel, normal smiling Mr. Incredible)",
            "after":  "The horrible revelation that ruined you — what you know NOW (LEFT panel, dark uncanny Mr. Incredible)",
        },
    ),

    # ── Midwit Bell Curve ────────────────────────────────────────────────────
    # 3-zone horizontal: left = low-IQ simple, center-top = midwit overcomplicated,
    # right = high-IQ returning to simplicity
    "midwit_bell_curve": TemplateConfig(
        template_id="midwit_bell_curve",
        text_boxes=[
            TextBoxConfig("simple_take",      x_pct=2,  y_pct=55, w_pct=28, h_pct=40, font_size_pct=4.5),
            TextBoxConfig("midwit_take",      x_pct=32, y_pct=2,  w_pct=36, h_pct=38, font_size_pct=4.5),
            TextBoxConfig("enlightened_take", x_pct=70, y_pct=55, w_pct=28, h_pct=40, font_size_pct=4.5),
        ],
        box_descriptions={
            "simple_take":      "The low-effort answer that is ironically correct (left, low-IQ side)",
            "midwit_take":      "The overthought, complicated, 'actually...' take that is wrong (center, midwit peak)",
            "enlightened_take": "The galaxy-brained sage who arrives at the same simple answer (right, high-IQ side)",
        },
    ),

    # ── Coldplay Kiss Cam Caught ─────────────────────────────────────────────
    # Concert jumbotron: two people caught together publicly
    "kiss_cam_caught": TemplateConfig(
        template_id="kiss_cam_caught",
        text_boxes=[
            TextBoxConfig("person_1",       x_pct=2,  y_pct=3,  w_pct=46, h_pct=22, font_size_pct=5),
            TextBoxConfig("person_2",       x_pct=52, y_pct=3,  w_pct=46, h_pct=22, font_size_pct=5),
            TextBoxConfig("caught_context", x_pct=5,  y_pct=78, w_pct=90, h_pct=18, font_size_pct=5),
        ],
        box_descriptions={
            "person_1":       "Who is in the first frame — the person expecting privacy (left)",
            "person_2":       "Who they are caught being with — the unexpected or awkward company (right)",
            "caught_context": "What makes the pairing devastating — the relationship or event that makes this exposure the worst possible timing",
        },
    ),

    # ── Well Yes But Actually No ─────────────────────────────────────────────
    # Pirate saying the phrase — "Well yes, but actually no" is baked into image
    "well_yes_but_actually_no": TemplateConfig(
        template_id="well_yes_but_actually_no",
        text_boxes=[
            TextBoxConfig("the_claim", x_pct=5, y_pct=2, w_pct=90, h_pct=25, font_size_pct=6),
        ],
        box_descriptions={
            "the_claim": "The technically-true statement the pirate is about to contradict. Do NOT write 'well yes but actually no' — that phrase is already baked into the image.",
        },
    ),

    # ── Ah Shit Here We Go Again ─────────────────────────────────────────────
    # GTA San Andreas loading screen — "Ah shit, here we go again." is baked in
    "ah_shit_here_we_go_again": TemplateConfig(
        template_id="ah_shit_here_we_go_again",
        text_boxes=[
            TextBoxConfig("situation", x_pct=5, y_pct=3, w_pct=90, h_pct=22, font_size_pct=6),
        ],
        box_descriptions={
            "situation": "What dreaded recurring situation is starting again. Do NOT write 'ah shit here we go again' — that line is already baked into the image.",
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
