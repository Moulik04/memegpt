"""
One-off generator for the 50 static "under construction" gag memes shown
on the coming-soon page's floating cards (frontend/src/app/maintenance/).

Reuses the real compositor (image_processing/compositor.py's compose_meme)
so output matches real MemeGPT quality (fonts, wrapping, watermark,
stroke) — but compositor.py's own `save_meme` binding is monkeypatched for
the duration of this script to write straight to
frontend/public/maintenance/ instead of wherever the real backend/.env
points (R2 in production-configured local envs). This guarantees zero
writes to the real R2 bucket regardless of what credentials happen to be
configured — these are throwaway gag assets, not real product data, and
don't belong in production storage. (Nothing here touches Postgres either
— compose_meme() never calls db.insert_meme; that only happens in
routers/chat.py, not the compositor.)

Run: python scripts/generate_maintenance_memes.py (from the repo root) —
matches dummy_template_test.py's "no services needed" precedent. Adds
backend/ to sys.path itself below so backend's own absolute imports
(`from storage import ...`, `from image_processing... import ...`) resolve
without needing backend/ as the working directory.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
OUT_DIR = REPO_ROOT / "frontend" / "public" / "maintenance"
sys.path.insert(0, str(BACKEND_DIR))

@dataclass
class _LocalSavedMeme:
    meme_id: str
    url: str
    path: Path


async def _save_locally_only(png_bytes: bytes, meme_id: str | None = None) -> _LocalSavedMeme:
    """Replaces compositor.save_meme for this script's duration — writes
    only to frontend/public/maintenance/, never touches R2 or any network
    call, regardless of backend/.env's real R2_* configuration."""
    assert meme_id is not None, "every call site below passes an explicit meme_id"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{meme_id}.png"
    path.write_bytes(png_bytes)
    return _LocalSavedMeme(meme_id=meme_id, url=f"/maintenance/{meme_id}.png", path=path)


import image_processing.compositor as compositor  # noqa: E402

# compositor.py does `from storage import save_meme` (a direct name import,
# not `import storage`), so it holds its own independent module-level
# binding — patching storage.save_meme would NOT reach the call compose_meme()
# actually makes. Must patch compositor's own bound name instead.
compositor.save_meme = _save_locally_only

compose_meme = compositor.compose_meme

# (template_id, {box_label: caption}) — captions written against the REAL
# per-template box schema (image_processing/template_configs.py), verified
# live via get_config(tid).text_boxes before writing any of these, since
# several templates have custom multi-box layouts (not just top/bottom).
MEMES: list[tuple[str, dict[str, str]]] = [
    ("hide_the_pain_harold", {"public_face": "EVERYTHING IS UNDER CONTROL", "inner_reality": "THE DEPLOY HAS FAILED FOUR TIMES TODAY"}),
    ("this_is_fine", {"situation": "THE SERVERS ARE HELD TOGETHER BY HOPE AND ONE VERY TIRED DEVELOPER"}),
    ("waiting_skeleton", {"top_text": "YOU, REFRESHING MEMEGPT.COM", "bottom_text": "EVERY 10 MINUTES, FOREVER"}),
    ("expanding_brain", {
        "level_1": "TAKE THE SITE DOWN FOR 5 MINUTES",
        "level_2": "TAKE IT DOWN FOR AN HOUR",
        "level_3": "TAKE IT DOWN FOR A FULL DAY",
        "level_4": "REBUILD THE ENTIRE MULTIVERSE INSTEAD",
    }),
    ("drake", {"rejected_option": "QUIETLY PATCHING A SMALL BUG", "approved_option": "PUTTING UP 'CLOSED FOR RENOVATIONS' AND VANISHING"}),
    ("grus_plan", {
        "step_1": "TAKE THE SITE DOWN FOR QUICK MAINTENANCE",
        "step_2": "FIX ONE SMALL THING",
        "step_3": "GET DISTRACTED ADDING 40 NEW FEATURES",
        "step_4": "GET DISTRACTED ADDING 40 NEW FEATURES",
    }),
    ("panik_kalm_panik", {"top_text": "SITE'S DOWN! ...OH WAIT, IT'S JUST MAINTENANCE", "bottom_text": "IT'S BEEN SCHEDULED FOR THREE DAYS"}),
    ("surprised_pikachu", {"setup": "TURNED OFF THE SITE FOR '10 MINUTES OF MAINTENANCE'", "reaction": "IT'S BEEN A WEEK"}),
    ("buff_doge_vs_cheems", {"buff_doge": "MEMEGPT WHEN WE'RE BACK ONLINE", "cheems": "MEMEGPT'S SERVER RIGHT NOW"}),
    ("mocking_spongebob", {"top_text": "'IT'LL ONLY TAKE A FEW MINUTES'", "bottom_text": "iT'lL oNlY tAkE a FeW mInUtEs"}),
    ("one_does_not_simply", {"top_text": "ONE DOES NOT SIMPLY", "bottom_text": "SHIP A REBUILD WITHOUT DOWNTIME"}),
    ("change_my_mind", {"opinion": "DOWNTIME BUILDS CHARACTER"}),
    ("two_buttons", {"button_1": "WAIT PATIENTLY", "button_2": "REFRESH FOR THE 100TH TIME"}),
    ("evil_kermit", {"regular_kermit": "JUST WAIT FOR THE OFFICIAL ANNOUNCEMENT", "evil_kermit": "REFRESH THE PAGE ONE MORE TIME"}),
    ("woman_yelling_at_cat", {"yelling_woman": "WHY IS THE SITE STILL DOWN", "confused_cat": "IT'S GETTING BETTER. RELAX."}),
    ("boardroom_meeting_suggestion", {
        "suggestion": "LET'S TAKE THE SITE DOWN FOR JUST ONE DAY",
        "person_1": "GREAT IDEA",
        "person_2": "LOVE THAT FOR US",
        "person_3": "SHIP IT",
        "reaction": "FIVE DAYS LATER...",
    }),
    ("epic_handshake", {"top_text": "PEOPLE WHO WANTED NEW FEATURES", "bottom_text": "PEOPLE WHO WANTED BUG FIXES — BOTH GOT DOWNTIME"}),
    ("tuxedo_winnie_the_pooh", {"top_text": "THE SITE IS DOWN", "bottom_text": "WE ARE UNDERGOING A COMPREHENSIVE INFRASTRUCTURE REVITALIZATION"}),
    ("left_exit_12", {"car": "MEMEGPT", "straight": "SHIP THE SMALL BUGFIX", "exit": "REBUILD THE ENTIRE APP INSTEAD"}),
    ("anakin_padme", {"anakin_says": "WE'RE JUST DOING A QUICK UPDATE", "padme_assumes": "RIGHT?", "anakin_silent": "...", "padme_nervous": "RIGHT?"}),
    ("uno_draw_25_cards", {"top_text": "JUST FIX THE ONE BUG", "bottom_text": "REWRITE THE ENTIRE BACKEND INSTEAD"}),
    ("leonardo_dicaprio_cheers", {"top_text": "SPOTTING THE EXACT MOMENT", "bottom_text": "THE NEW MEMEGPT FINALLY GOES LIVE"}),
    ("laughing_leo", {"top_text": "THE OLD SITE'S BUGS", "bottom_text": "ONE LAST TIME BEFORE THEY'RE GONE"}),
    ("all_my_homies_hate", {"top_text": "ALL MY HOMIES HATE", "bottom_text": "LOADING SPINNERS"}),
    ("spiderman_pointing_at_spiderman", {"top_text": "THE OLD SITE", "bottom_text": "THE NEW SITE (BOTH BLAMING EACH OTHER FOR THE DOWNTIME)"}),
    ("flex_tape", {"top_text": "THE FIX FOR EVERY BUG", "bottom_text": "WE FOUND DURING THIS REBUILD"}),
    ("marked_safe_from", {"top_text": "MARKED SAFE FROM", "bottom_text": "THE OLD LOADING SPINNER TODAY"}),
    ("clown_applying_makeup", {"top_text": "SAYING WE'D BE QUICK", "bottom_text": "STILL HERE SIX HOURS LATER"}),
    ("running_away_balloon", {"top_text": "CHASING", "bottom_text": "'JUST ONE MORE FEATURE BEFORE WE RELAUNCH'"}),
    ("absolute_cinema", {"top_text": "THIS UPDATE", "bottom_text": "WHEN IT FINALLY SHIPS"}),
    ("gus_fring_we_are_not_the_same", {"top_text": "WE ARE NOT THE SAME", "bottom_text": "WE HAVE A STATUS PAGE"}),
    ("star_wars_yoda", {"top_text": "BACK ONLINE SOON", "bottom_text": "WE WILL BE"}),
    ("the_rock_driving", {"top_text": "SUDDENLY REMEMBERING", "bottom_text": "WE NEVER UPDATED THE STATUS PAGE"}),
    ("friendship_ended", {"top_text": "FRIENDSHIP ENDED WITH OLD MEMEGPT", "bottom_text": "NEW MEMEGPT IS MY BEST FRIEND NOW"}),
    ("but_that_s_none_of_my_business", {"top_text": "THE DEPLOY HAS BEEN 'ALMOST DONE' FOR SIX HOURS", "bottom_text": "BUT THAT'S NONE OF MY BUSINESS"}),
    ("scooby_doo_mask_reveal", {"top_text": "AND THE BUG WAS", "bottom_text": "A MISSING SEMICOLON, ALL ALONG"}),
    ("the_scroll_of_truth", {"top_text": "READING THE CHANGELOG", "bottom_text": "THROWING IT AWAY IMMEDIATELY"}),
    ("sad_pablo", {"top_text": "WAITING FOR THE SITE TO COME BACK", "bottom_text": "STILL WAITING"}),
    ("domino_effect", {"top_text": "ONE TYPO IN THE CONFIG", "bottom_text": "THE ENTIRE SITE GOES DOWN"}),
    ("bike_fall", {"top_text": "GOT DISTRACTED ADDING ONE MORE FEATURE", "bottom_text": "CRASHED THE WHOLE DEPLOY"}),
    ("two_paths", {"top_text": "SHIP IT NOW", "bottom_text": "SHIP IT RIGHT"}),
    ("blank_nut_button", {"top_text": "REFRESHING MEMEGPT.COM", "bottom_text": "EVERY 30 SECONDS, COMPULSIVELY"}),
    ("i_m_the_captain_now", {"top_text": "THE NEW MEMEGPT", "bottom_text": "SEIZING CONTROL FROM THE OLD ONE"}),
    ("roll_safe_think_about_it", {"top_text": "CAN'T HAVE BUGS IN PRODUCTION", "bottom_text": "IF PRODUCTION IS DOWN"}),
    ("theyre_the_same_picture", {"top_text": "'QUICK MAINTENANCE'", "bottom_text": "'COMPLETE REBUILD'"}),
    ("sad_hamster", {"top_text": "ME", "bottom_text": "BEGGING THE DEVS TO HURRY UP"}),
    ("chill_guy", {"top_text": "MEMEGPT, COMPLETELY UNBOTHERED", "bottom_text": "WHILE EVERYONE WAITS"}),
    ("ah_shit_here_we_go_again", {"situation": "ANOTHER 'JUST 10 MORE MINUTES' UPDATE"}),
    ("math_lady", {"top_text": "TRYING TO CALCULATE", "bottom_text": "HOW MUCH LONGER THE MAINTENANCE WILL TAKE"}),
    ("mr_incredible_uncanny", {"before": "THE SITE IS UNDER MAINTENANCE", "after": "IT'S BEEN UNDER MAINTENANCE FOR A WEEK"}),
]


async def main() -> None:
    assert len(MEMES) == 50, f"expected 50 memes, got {len(MEMES)}"
    assert len({tid for tid, _ in MEMES}) == 50, "expected 50 distinct templates, found duplicates"

    ok, failed = 0, []
    for template_id, texts in MEMES:
        try:
            saved = await compose_meme(template_id, texts)
            # compose_meme() names the file after a random generate_meme_id(),
            # not the template_id (that random id is meant for real product
            # use — durable share links, provenance tags — none of which
            # applies here). Rename to the template_id so the frontend can
            # reference these by a predictable, meaningful filename.
            final_path = OUT_DIR / f"{template_id}.png"
            saved.path.rename(final_path)
            print(f"  [OK] {template_id} -> {final_path.name}")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {template_id}: {type(e).__name__}: {e}")
            failed.append(template_id)

    print(f"\n{ok}/{len(MEMES)} generated into {OUT_DIR}")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
