"""
Seed script — downloads real meme template images from Imgflip's free public
API and upserts them into ChromaDB so the backend can serve them immediately.

Run once before starting the server, or re-run to pick up new templates:

    cd memegpt/
    python scripts/seed_templates.py

No API keys required — Imgflip's /get_memes endpoint is fully public.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from vector_db.chroma_client import init_chroma, upsert_template  # noqa: E402

TEMPLATES_DIR = BACKEND_DIR / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

IMGFLIP_API = "https://api.imgflip.com/get_memes"

# Maps Imgflip display name → (our template_id, tags, description)
# Description text is what ChromaDB embeds for semantic search — write it
# the way a user would describe the situation that calls for this meme.
TEMPLATE_CATALOG: dict[str, tuple[str, list[str], str]] = {
    "Drake Hotline Bling": (
        "drake",
        ["approval", "rejection", "comparison", "preference"],
        "Drake rejecting one thing and approving another. Use when comparing two options "
        "where you strongly prefer the second one over the first.",
    ),
    "Distracted Boyfriend": (
        "distracted_boyfriend",
        ["distraction", "temptation", "betrayal", "switching"],
        "Man ignoring his girlfriend to look at another woman. Use when someone abandons "
        "something they had for a shiny new thing.",
    ),
    "Two Buttons": (
        "two_buttons",
        ["dilemma", "choice", "stress", "decision"],
        "Sweating man nervously pressing two buttons. Use for impossible choices or "
        "decisions that are both bad.",
    ),
    "Change My Mind": (
        "change_my_mind",
        ["opinion", "debate", "controversial", "argument"],
        "Man sitting at a table with a sign. Use for stating a hot take or unpopular "
        "opinion and daring someone to disagree.",
    ),
    "Expanding Brain": (
        "expanding_brain",
        ["galaxy brain", "escalation", "intelligence", "tiers"],
        "Brain expanding through multiple levels. Use for showing a progression from "
        "basic/dumb to enlightened/ridiculous thinking.",
    ),
    "This Is Fine": (
        "this_is_fine",
        ["denial", "chaos", "calm", "disaster"],
        "Dog sitting calmly in a room on fire. Use when someone is ignoring an obvious "
        "disaster around them.",
    ),
    "Doge": (
        "doge",
        ["wow", "such", "very", "dog", "impressed"],
        "Shiba Inu with multicolored text. Use for expressing amazement or sarcastic "
        "enthusiasm with 'wow' and 'such' phrases.",
    ),
    "Success Kid": (
        "success_kid",
        ["success", "win", "victory", "small wins", "fist pump"],
        "Kid clenching fist triumphantly. Use for celebrating small or unexpected victories.",
    ),
    "One Does Not Simply": (
        "one_does_not_simply",
        ["difficulty", "impossible", "lord of the rings", "boromir"],
        "Boromir from Lord of the Rings. Use for pointing out that something is much "
        "harder than people think.",
    ),
    "Woman Yelling At Cat": (
        "woman_yelling_at_cat",
        ["argument", "yelling", "confused", "reaction", "cat"],
        "Woman pointing and yelling, cat looking confused. Use for two-sided disagreements "
        "or when someone overreacts to something trivial.",
    ),
    "Surprised Pikachu": (
        "surprised_pikachu",
        ["surprised", "shocked", "obvious", "consequences"],
        "Pikachu with an open mouth looking shocked. Use when someone is surprised by "
        "completely predictable consequences of their actions.",
    ),
    "Gru's Plan": (
        "grus_plan",
        ["plan", "backfire", "own goal", "mistake"],
        "Gru presenting a 4-panel plan where the last step reveals he didn't think it "
        "through. Use for plans that have an obvious flaw.",
    ),
    "Mocking Spongebob": (
        "mocking_spongebob",
        ["mocking", "sarcasm", "mimicking", "alternating caps"],
        "Spongebob in a weird pose. Use for mockingly repeating what someone said in a "
        "sarcastic alternating-caps way.",
    ),
    "Hide the Pain Harold": (
        "hide_the_pain_harold",
        ["pain", "smile", "suffering", "pretending"],
        "Older man smiling while clearly in pain. Use for faking happiness while "
        "something is clearly wrong.",
    ),
    "Buff Doge vs. Cheems": (
        "buff_doge_vs_cheems",
        ["comparison", "then vs now", "strong vs weak", "buff"],
        "Buff muscular doge on the left vs small sad doge on right. Use for "
        "then-vs-now or strong-vs-weak comparisons.",
    ),
    "Batman Slapping Robin": (
        "batman_slapping_robin",
        ["shut up", "slap", "batman", "correction"],
        "Batman slapping Robin mid-sentence. Use when you want to interrupt and "
        "correct someone who is about to say something wrong or annoying.",
    ),
    "Left Exit 12 Off Ramp": (
        "left_exit_12",
        ["choice", "swerve", "priorities", "distraction"],
        "Car swerving off a highway to take an exit. Use when someone abandons the "
        "sensible path for something tempting.",
    ),
    "Always Has Been": (
        "always_has_been",
        ["always has been", "astronaut", "realization", "dark truth"],
        "Two astronauts, one pointing a gun. Use for revealing that something was always "
        "a certain way — usually a dark or ironic truth.",
    ),
    "Galaxy Brain": (
        "galaxy_brain",
        ["logic", "big brain", "overthinking", "convoluted"],
        "Expanding head meme showing increasingly absurd logic. Use for convoluted "
        "reasoning that somehow arrives at a wild conclusion.",
    ),
    "Anakin Padme 4 Panel": (
        "anakin_padme",
        ["right?", "nervous", "star wars", "expectation vs reality"],
        "Anakin and Padme from Star Wars — Padme expecting confirmation, Anakin "
        "silent. Use for when someone assumes a positive outcome that isn't happening.",
    ),
}


def fetch_imgflip_memes() -> list[dict]:
    print("Fetching meme list from Imgflip API...")
    r = httpx.get(IMGFLIP_API, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Imgflip API returned failure: {data}")
    return data["data"]["memes"]


def download_image(url: str, dest: Path) -> bool:
    if dest.exists():
        print(f"  [skip] {dest.name} already on disk")
        return True
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
    imgflip_memes = fetch_imgflip_memes()

    # Build lookup: Imgflip display name → meme dict
    imgflip_by_name = {m["name"]: m for m in imgflip_memes}

    seeded = 0
    skipped = 0

    for display_name, (template_id, tags, description) in TEMPLATE_CATALOG.items():
        meme = imgflip_by_name.get(display_name)
        if not meme:
            print(f"[warn] '{display_name}' not found in Imgflip response — skipping")
            skipped += 1
            continue

        # Determine file extension from URL
        url: str = meme["url"]
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        dest = TEMPLATES_DIR / f"{template_id}{ext}"

        print(f"[{template_id}] Downloading '{display_name}'...")
        ok = download_image(url, dest)
        if not ok:
            skipped += 1
            continue

        # Seed ChromaDB
        upsert_template(
            template_id=template_id,
            name=display_name,
            tags=tags,
            description=description,
        )
        print(f"  [ok] Seeded ChromaDB entry for '{template_id}'")
        seeded += 1

        # Small delay to be polite to Imgflip
        time.sleep(0.1)

    print(f"\nDone. Seeded: {seeded}  |  Skipped: {skipped}")
    print(f"Templates saved to: {TEMPLATES_DIR.resolve()}")
    print("You can now start the backend: uvicorn main:app --reload")


if __name__ == "__main__":
    main()
