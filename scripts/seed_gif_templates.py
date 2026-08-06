"""
Seed the 3 curated animated GIF templates.

Unlike scripts/seed_templates.py's Imgflip fetch, Imgflip's own "gif" type
templates turn out to be served as .mp4 internally, not actual .gif files
— Pillow can't decode those, and converting them would need ffmpeg,
contradicting the Pillow-only rendering path this app uses elsewhere. So
these 3 are instead sourced from Wikimedia Commons, whose hosting policy
requires freely-licensed or public-domain media — real, genuinely
multi-frame animated GIFs, each verified via Image.open(path).n_frames > 1
before being accepted.

Downloads into backend/templates/ and calls upsert_template() directly —
NOT gated on ChromaDB being empty (unlike main.py's _auto_seed_if_empty),
which is what actually gets these into an already-seeded collection (a
developer's existing local Chroma, or eventually production after a
redeploy) rather than only a from-scratch one.

Run:
    cd backend && source .venv/bin/activate
    python3 ../scripts/seed_gif_templates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from vector_db.chroma_client import init_chroma, upsert_template  # noqa: E402

TEMPLATES_DIR = BACKEND_DIR / "templates"

# (template_id, display name, source URL, tags, description)
GIF_TEMPLATES: list[tuple[str, str, str, list[str], str]] = [
    (
        "party_parrot",
        "Party Parrot",
        "https://upload.wikimedia.org/wikipedia/commons/9/92/Party_Parrot.gif",
        ["hype", "celebration", "excited", "party"],
        "A bobbing rainbow parrot celebrating. Use for pure, uncomplicated hype and excitement.",
    ),
    (
        "floss_dance",
        "Floss Dance",
        "https://upload.wikimedia.org/wikipedia/commons/2/2f/Floss_%28dance%29.gif",
        ["dance", "goofy", "victory", "showing off"],
        "A goofy, exaggerated victory dance. Use for silly, over-the-top celebration of a small win.",
    ),
    (
        "spinning_dancer",
        "Spinning Dancer",
        "https://upload.wikimedia.org/wikipedia/commons/2/21/Spinning_Dancer.gif",
        ["illusion", "perception", "disagreement", "same thing different view"],
        "A silhouette dancer that appears to spin either direction depending on the viewer. "
        "Use for two people seeing the same situation completely differently, with no clear right answer.",
    ),
]


def download(url: str, dest: Path) -> bool:
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        print(f"  [error] Failed to download {url}: {exc}")
        return False


def main() -> None:
    init_chroma()
    seeded = 0
    for template_id, name, url, tags, description in GIF_TEMPLATES:
        dest = TEMPLATES_DIR / f"{template_id}.gif"
        print(f"[{template_id}] {name}")

        if not dest.exists():
            if not download(url, dest):
                continue
        else:
            print("  [skip download] already on disk")

        try:
            img = Image.open(dest)
            n_frames = getattr(img, "n_frames", 1)
        except Exception as exc:
            print(f"  [error] Not a valid image: {exc}")
            dest.unlink(missing_ok=True)
            continue

        if n_frames <= 1:
            print(f"  [reject] Only {n_frames} frame(s) — not genuinely animated, skipping.")
            dest.unlink(missing_ok=True)
            continue

        upsert_template(template_id=template_id, name=name, tags=tags, description=description)
        print(f"  [ok] {n_frames} frames, seeded into ChromaDB")
        seeded += 1

    print(f"\nDone. Seeded {seeded}/{len(GIF_TEMPLATES)} GIF templates.")
    print("Remember: each also needs a TemplateConfig(is_gif=True, ...) entry in "
          "image_processing/template_configs.py and a USE_WHEN entry in "
          "nlp/intent_router.py — both already added for the 3 templates above.")


if __name__ == "__main__":
    main()
