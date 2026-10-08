"""
Does the one-call photo check block what the separate check blocks?

uploads/moderation.py has two ways to check a photo: moderate_image() (the
safety verdict alone) and moderate_and_describe_image() (the verdict and
the description in one call, behind settings.photo_single_call). The second
must never be more lenient than the first. This runs both on the same
images and compares.

It FAILS (exit 1) if any image the separate check blocked was passed by the
one-call check. The other direction is reported, not failed: blocking more
is the safe way to be wrong.

    cd backend && python -m scripts.eval_photo_single_call                 # the default set
    cd backend && python -m scripts.eval_photo_single_call path/to/images  # every image in a folder

REAL MODEL CALLS. Two per image, about 2,000 tokens each on the vision
model, against a daily budget of 200,000 that production shares. The script
prints its estimate and asks before the first call (--yes skips the
question). It paces itself under the per-minute limit and stops the moment
the daily budget runs out, reporting only the images both checks finished.

Images are never written anywhere and no model output is printed beyond
the verdict and its category.

The default set is catalog templates: the ones a strict classifier is most
likely to block, plus a few plainly harmless ones as controls. A catalog
image is a known quantity, which a pile of test photos is not. To check
against real refusals, point it at a folder.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from PIL import Image

from config import get_settings
from nlp.llm_client import daily_limit_active
from uploads.moderation import (
    CATEGORY_DAILY_LIMIT,
    CATEGORY_RATE_LIMITED,
    ModerationResult,
    moderate_and_describe_image,
    moderate_image,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

DEFAULT_TEMPLATE_IDS = [
    # Weapons, blood, disasters, a slap: where a refusal is most likely.
    "who_killed_hannibal",
    "grim_reaper_knocking_door",
    "a_train_hitting_a_school_bus",
    "george_bush_9_11",
    "batman_slapping_robin",
    "anime_girl_hiding_from_terminator",
    "mother_ignoring_kid_drowning_in_a_pool",
    "disaster_girl",
    # Controls.
    "drake",
    "waiting_skeleton",
    "sad_hamster",
    "one_does_not_simply",
]

_TOKENS_PER_CALL = 2_000  # measured 1.9k-2.2k per photo call, 2026-10-07
_DAILY_BUDGET = 200_000
_PACING_SECONDS = 16  # 8,000 tokens a minute allows one ~2k call about every 15s
_COULD_NOT_RUN = {CATEGORY_RATE_LIMITED, CATEGORY_DAILY_LIMIT, "moderation_unavailable"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _find_images(folder: Path | None) -> list[Path]:
    if folder is not None:
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
    found = []
    for template_id in DEFAULT_TEMPLATE_IDS:
        matches = [p for p in _TEMPLATES_DIR.glob(f"{template_id}.*") if p.suffix.lower() in _IMAGE_SUFFIXES]
        if matches:
            found.append(matches[0])
        else:
            print(f"  (no image for {template_id}, skipped)")
    return found


def _label(result: ModerationResult) -> str:
    return "pass" if result.passed else f"BLOCK ({result.category})"


async def _paced(check, image: Image.Image, first: bool) -> ModerationResult:
    if not first:
        await asyncio.sleep(_PACING_SECONDS)
    return await check(image)


async def run(paths: list[Path]) -> int:
    rows: list[tuple[str, ModerationResult, ModerationResult]] = []
    stopped = False
    for i, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        separate = await _paced(moderate_image, image, first=(i == 0))
        combined = await _paced(moderate_and_describe_image, image, first=False)
        if daily_limit_active(get_settings().moderation_model):
            print(f"\nSTOPPED at image {i + 1} of {len(paths)}: the model's daily budget is used up.")
            stopped = True
            break
        if separate.category in _COULD_NOT_RUN or combined.category in _COULD_NOT_RUN:
            print(f"  [not compared] {path.name}: a check could not be run")
            continue
        rows.append((path.name, separate, combined))
        print(f"  {path.name:55s} separate: {_label(separate):22s} one call: {_label(combined)}")

    more_lenient = [r for r in rows if not r[1].passed and r[2].passed]
    stricter = [r for r in rows if r[1].passed and not r[2].passed]
    undescribed = [r for r in rows if r[2].passed and not r[2].description]
    blocked_by_separate = sum(1 for r in rows if not r[1].passed)

    print("\n" + "=" * 70)
    print(f"Compared:                              {len(rows)} of {len(paths)}")
    print(f"Blocked by the separate check:         {blocked_by_separate}")
    print(f"  of those, passed by the one call:    {len(more_lenient)}  <- must be 0")
    print(f"Passed separately, blocked by one call: {len(stricter)}")
    print(f"Passed by one call with no description: {len(undescribed)}  (costs a second call each)")
    for name, _, _ in more_lenient:
        print(f"  MORE LENIENT: {name}")
    for name, _, combined in stricter:
        print(f"  stricter: {name} ({combined.category})")
    if blocked_by_separate == 0:
        print("\nNothing in this set was blocked by the separate check, so this run says")
        print("nothing about whether the one call blocks the same things.")
    if stopped:
        print("\nIncomplete run: the result covers only the images listed above.")
    return 1 if more_lenient else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", nargs="?", type=Path, help="Folder of images. Default: a set of catalog templates.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation question.")
    args = parser.parse_args()

    if not get_settings().groq_api_key:
        sys.exit("GROQ_API_KEY is not set. Both checks fail closed without it, so there is nothing to compare.")

    paths = _find_images(args.folder)
    if not paths:
        sys.exit("No images found.")
    estimate = len(paths) * 2 * _TOKENS_PER_CALL
    print(
        f"{len(paths)} images, 2 real model calls each: about {estimate:,} tokens "
        f"({100 * estimate / _DAILY_BUDGET:.0f}% of the daily budget), "
        f"about {len(paths) * 2 * _PACING_SECONDS // 60 + 1} minutes."
    )
    if not args.yes and input("Run it? [y/N] ").strip().lower() != "y":
        sys.exit("Not run.")

    sys.exit(asyncio.run(run(paths)))


if __name__ == "__main__":
    main()
