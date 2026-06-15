"""
Seed script — downloads ALL top-100 meme template images from Imgflip's free
public API and upserts them into ChromaDB.

TEMPLATE_CATALOG holds curated metadata for well-known templates.
Any template returned by Imgflip that isn't in the catalog gets auto-seeded
with generated metadata so nothing is skipped.

Run once before starting the server (or re-run to refresh):

    cd backend && source .venv/bin/activate
    python3 ../scripts/seed_templates.py
"""

from __future__ import annotations

import re
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


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# Curated metadata for key templates — richer descriptions for better semantic search
TEMPLATE_CATALOG: dict[str, tuple[str, list[str], str]] = {
    "Drake Hotline Bling": (
        "drake", ["approval", "rejection", "comparison", "preference"],
        "Drake rejecting one thing and approving another. Use when comparing two options where you strongly prefer the second one.",
    ),
    "Distracted Boyfriend": (
        "distracted_boyfriend", ["distraction", "temptation", "betrayal", "switching"],
        "Man ignoring his girlfriend to look at another woman. Use when someone abandons something they had for a shiny new thing.",
    ),
    "Two Buttons": (
        "two_buttons", ["dilemma", "choice", "stress", "decision"],
        "Sweating man nervously pressing two buttons. Use for impossible choices or decisions that are both bad or both tempting.",
    ),
    "Change My Mind": (
        "change_my_mind", ["opinion", "debate", "controversial", "argument"],
        "Man sitting at a table with a sign. Use for stating a hot take or unpopular opinion and daring someone to disagree.",
    ),
    "Expanding Brain": (
        "expanding_brain", ["galaxy brain", "escalation", "intelligence", "tiers"],
        "Brain expanding through multiple levels. Use for showing a progression from basic/dumb to enlightened/ridiculous thinking.",
    ),
    "This Is Fine": (
        "this_is_fine", ["denial", "chaos", "calm", "disaster", "fire"],
        "Dog sitting calmly in a room on fire. Use when someone is ignoring an obvious disaster around them.",
    ),
    "Doge": (
        "doge", ["wow", "such", "very", "dog", "impressed", "comic sans"],
        "Shiba Inu with multicolored scattered text. Use for expressing amazement with 'wow', 'such', 'very', 'much' phrases.",
    ),
    "Success Kid": (
        "success_kid", ["success", "win", "victory", "small wins", "fist pump"],
        "Kid clenching fist triumphantly. Use for celebrating small or unexpected victories.",
    ),
    "One Does Not Simply": (
        "one_does_not_simply", ["difficulty", "impossible", "boromir", "lotr"],
        "Boromir from Lord of the Rings. Use for pointing out that something is much harder than people think.",
    ),
    "Woman Yelling At Cat": (
        "woman_yelling_at_cat", ["argument", "yelling", "confused", "reaction", "cat"],
        "Woman pointing and yelling, cat looking confused. Use for two-sided disagreements or when someone overreacts to something trivial.",
    ),
    "Surprised Pikachu": (
        "surprised_pikachu", ["surprised", "shocked", "obvious", "consequences"],
        "Pikachu with an open mouth looking shocked. Use when someone is surprised by completely predictable consequences of their own actions.",
    ),
    "Gru's Plan": (
        "grus_plan", ["plan", "backfire", "own goal", "mistake"],
        "Gru presenting a 4-panel plan where the last step reveals he didn't think it through. Use for plans with an obvious flaw.",
    ),
    "Mocking Spongebob": (
        "mocking_spongebob", ["mocking", "sarcasm", "mimicking", "alternating caps"],
        "Spongebob in a weird pose. Use for mockingly repeating what someone said in alternating caps.",
    ),
    "Hide the Pain Harold": (
        "hide_the_pain_harold", ["pain", "smile", "suffering", "pretending"],
        "Older man smiling while clearly in pain. Use for faking happiness while something is clearly wrong.",
    ),
    "Buff Doge vs. Cheems": (
        "buff_doge_vs_cheems", ["comparison", "then vs now", "strong vs weak", "buff"],
        "Buff muscular doge vs small sad doge. Use for then-vs-now or strong-vs-weak comparisons.",
    ),
    "Batman Slapping Robin": (
        "batman_slapping_robin", ["shut up", "slap", "batman", "correction"],
        "Batman slapping Robin mid-sentence. Use to interrupt and correct someone who is about to say something wrong.",
    ),
    "Left Exit 12 Off Ramp": (
        "left_exit_12", ["choice", "swerve", "priorities", "distraction", "highway"],
        "Car swerving off a highway to take an exit. Use when someone abandons the sensible path for something tempting.",
    ),
    "Always Has Been": (
        "always_has_been", ["always has been", "astronaut", "realization", "dark truth"],
        "Two astronauts, one pointing a gun. Use for revealing that something was always a certain way — usually a dark truth.",
    ),
    "Galaxy Brain": (
        "galaxy_brain", ["logic", "big brain", "overthinking", "convoluted", "reasoning"],
        "Expanding head meme showing increasingly absurd logic. Use for convoluted reasoning that arrives at a wild conclusion.",
    ),
    "Anakin Padme 4 Panel": (
        "anakin_padme", ["right?", "nervous", "star wars", "expectation vs reality"],
        "Anakin and Padme from Star Wars — Padme expecting confirmation, Anakin silent. Use when someone assumes a positive outcome that isn't happening.",
    ),
    "Futurama Fry": (
        "futurama_fry", ["not sure if", "squinting", "skeptical", "suspicious"],
        "Fry squinting suspiciously. Use when you're not sure if something is real or just another thing masquerading as it.",
    ),
    "The Most Interesting Man In The World": (
        "the_most_interesting_man", ["interesting", "i don't always", "dos equis", "refined"],
        "The Most Interesting Man saying 'I don't always... but when I do...' Use for grandiose statements about your habits.",
    ),
    "Y U No": (
        "y_u_no", ["demand", "frustration", "why", "rage face"],
        "Rage face demanding to know why. Use when frustrated that someone won't just do the obvious thing.",
    ),
    "Ancient Aliens": (
        "ancient_aliens", ["aliens", "conspiracy", "explanation", "history channel"],
        "History Channel alien guy. Use for attributing something to aliens or a conspiracy when the answer is obvious.",
    ),
    "First World Problems": (
        "first_world_problems", ["privilege", "trivial", "complaint", "crying"],
        "Woman crying into her hand. Use for complaining dramatically about trivial first-world inconveniences.",
    ),
    "Bad Luck Brian": (
        "bad_luck_brian", ["bad luck", "worst case", "unfortunate", "backfire"],
        "Kid with yearbook photo looking confident but something terrible happens. Use for maximum bad luck scenarios.",
    ),
    "Good Guy Greg": (
        "good_guy_greg", ["nice", "considerate", "wholesome", "kind"],
        "Guy with a joint being unexpectedly nice. Use for showcasing unexpectedly wholesome or considerate behavior.",
    ),
    "Scumbag Steve": (
        "scumbag_steve", ["selfish", "obnoxious", "rude", "inconsiderate"],
        "Guy with a sideways cap being obnoxious. Use for calling out selfish or socially unaware behavior.",
    ),
    "Grumpy Cat": (
        "grumpy_cat", ["no", "refusal", "negative", "grumpy"],
        "Grumpy-faced cat. Use for categorical refusal or absolute negativity — 'No.' to everything.",
    ),
    "Philosoraptor": (
        "philosoraptor", ["philosophy", "deep thoughts", "question", "pondering"],
        "Velociraptor pondering existence. Use for posing a surprisingly deep philosophical question.",
    ),
    "Disaster Girl": (
        "disaster_girl", ["chaos", "smirk", "fire", "enjoying disaster"],
        "Little girl smiling in front of a burning building. Use for enjoying someone else's chaos from a safe distance.",
    ),
    "Monkey Puppet": (
        "monkey_puppet", ["awkward", "side eye", "uncomfortable", "pretend not to notice"],
        "Monkey side-eyeing with discomfort. Use for awkwardly looking away from something uncomfortable.",
    ),
    "Crying Cat": (
        "crying_cat", ["sad", "tears", "despair", "emotional"],
        "Cat with sad watery eyes. Use for genuine emotional pain or sadness, even over trivial things.",
    ),
    "Roll Safe": (
        "rollsafe", ["logic", "can't", "avoid", "clever"],
        "Man pointing to his head. Use for 'can't X if you never Y' — avoiding a problem through clever/flawed logic.",
    ),
    "Arthur Fist": (
        "arthur_fist", ["rage", "anger", "fist", "barely contained"],
        "Arthur the aardvark clenching his fist. Use for barely-contained rage at something infuriating.",
    ),
    "Kermit Tea": (
        "kermit_tea", ["none of my business", "passive aggressive", "but that's none of my business"],
        "Kermit sipping tea. Use for passive-aggressive observations about others while claiming it's 'none of my business'.",
    ),
    "Oprah You Get A": (
        "oprah", ["giving", "generosity", "everyone", "you get a car"],
        "Oprah excitedly pointing. Use for giving the same thing to absolutely everyone — wild generosity or equal distribution.",
    ),
    "Jack Sparrow Being Chased": (
        "jack_sparrow", ["running", "chased", "fleeing"],
        "Jack Sparrow being chased. Use for running away from responsibilities or being pursued by consequences.",
    ),
    "Giga Chad": (
        "giga_chad", ["chad", "confident", "unbothered", "sigma"],
        "Ultra-confident gigachad face. Use for making an extremely confident statement and refusing to apologize for it.",
    ),
    "Stonks": (
        "stonks", ["stocks", "profit", "business", "bad logic", "gains"],
        "Meme man with stocks going up. Use for making a terrible decision that somehow looks profitable on paper.",
    ),
    "Bernie I Am Once Again Asking": (
        "bernie_sanders", ["bernie", "asking", "mittens", "donation", "political"],
        "Bernie Sanders with mittens at inauguration. Use for making a recurring earnest request or stoic observation.",
    ),
    "Panik Kalm Panik": (
        "panik_kalm_panik", ["panic", "calm", "anxiety", "relief", "three panel"],
        "Three-panel meme: Panik → Kalm → Panik. Use for situations that seem bad, then fine, then bad again.",
    ),
    "Running Away Balloon": (
        "running_away_balloon", ["letting go", "priorities", "balloon", "what matters"],
        "Man letting go of balloon labeled something important to chase another. Use for misplaced priorities.",
    ),
    "Waiting Skeleton": (
        "waiting_skeleton", ["waiting", "still waiting", "forever", "skeleton"],
        "Skeleton sitting and waiting. Use for things that are taking forever or will never happen.",
    ),
    "Trade Offer": (
        "trade_offer", ["deal", "trade", "offer", "tiktok", "receive"],
        "I receive X. You receive Y. Use for lopsided or ironic deal proposals.",
    ),
    "They're The Same Picture": (
        "theyre_the_same_picture", ["same", "identical", "no difference", "dwight"],
        "Pam from The Office saying 'They're the same picture'. Use to point out two things are identical.",
    ),
    "Is This A Pigeon": (
        "is_this_a_pigeon", ["misidentifying", "wrong", "butterfly", "anime"],
        "Anime character misidentifying a butterfly as a pigeon. Use for confidently misidentifying something obvious.",
    ),
    "Ight Imma Head Out": (
        "ight_imma_head_out", ["leaving", "bye", "exit", "spongebob"],
        "Spongebob getting up from couch to leave. Use for immediately leaving when something awkward or bad happens.",
    ),
    "Among Us Ejected": (
        "among_us", ["impostor", "among us", "sus", "ejected"],
        "Among Us ejection screen. Use for identifying someone as a fraud, impostor, or suspicious character.",
    ),
    "Uno Reverse Card": (
        "uno_reverse", ["reverse", "uno", "back at you", "retaliation"],
        "Uno reverse card. Use for turning someone's argument or action right back on them.",
    ),
    "MegaMind No Bitches": (
        "megamind", ["no bitches", "megamind", "nobody", "technically"],
        "Megamind 'No' meme. Use for pointing out that technically you can't fail if you never try.",
    ),
    "The Rock Driving": (
        "the_rock_driving", ["oh no", "interesting", "concerned", "driving"],
        "The Rock alternating between concerned and interested while driving. Use for immediate course corrections in interest.",
    ),
    "My Plans vs 2020": (
        "my_plans", ["plans", "reality", "expectations vs reality", "ruined"],
        "My plans vs what actually happens. Use for expectation vs reality comparisons.",
    ),
    "Coffin Dance": (
        "coffin_dance", ["ghana", "coffin", "pallbearers", "deceased"],
        "Ghanaian pallbearers dancing with a coffin. Use for when something inevitably dies or ends.",
    ),
    "Daily Struggle": (
        "daily_struggle", ["struggle", "choice", "pointing", "hard decision"],
        "Man sweating choosing between two options. Use for difficult everyday decisions.",
    ),
    "Guys vs Girls Bathroom": (
        "guys_vs_girls_bathroom", ["bathroom", "gender", "comparison", "messy vs clean"],
        "Men's vs women's bathroom comparison. Use for contrasting how two groups approach the same thing.",
    ),
    "The Office": (
        "the_office", ["michael scott", "office", "no no no no", "that's what she said"],
        "The Office reaction meme. Use for reacting to something with Michael Scott energy.",
    ),
    "Drakeposting": (
        "drakeposting", ["drake", "no yes", "comparison"],
        "Drake meme variant. Use for rejecting one thing and approving another (same as drake).",
    ),
    "Spiderman Pointing": (
        "spiderman_pointing", ["pointing", "same", "identical", "you too"],
        "Two Spidermen pointing at each other. Use when two things or people are exactly the same.",
    ),
    "Be Like Bill": (
        "be_like_bill", ["smart", "bill", "be like bill", "example"],
        "Stick figure named Bill being sensible. Use for praising sensible behavior in contrast to what others do.",
    ),
    "That Would Be Great": (
        "that_would_be_great", ["office space", "bill lumbergh", "it would be great if"],
        "Bill Lumbergh from Office Space. Use for passive-aggressive requests framed as suggestions.",
    ),
    "Pepperidge Farm Remembers": (
        "pepperidge_farm", ["remember", "nostalgia", "back in my day", "pepperidge farm"],
        "Pepperidge Farm remembers. Use for nostalgia or pointing out how things used to be.",
    ),
    "I Should Have": (
        "i_should_have", ["regret", "hindsight", "should have", "obvious in retrospect"],
        "Realizing the obvious thing you should have done in hindsight.",
    ),
    "10 Guy": (
        "10_guy", ["high", "oblivious", "deep", "stoner", "profound"],
        "Guy who is clearly high making a surprisingly deep or completely dumb observation.",
    ),
    "If You Know What I Mean": (
        "if_you_know", ["mr bean", "wink", "innuendo", "nudge nudge"],
        "Mr Bean winking. Use for saying something with an implied double meaning.",
    ),
    "Laughing Tom Hanks": (
        "tom_hanks_laughing", ["laughing", "reaction", "humor", "tom hanks"],
        "Tom Hanks laughing. Use for finding something genuinely or sarcastically hilarious.",
    ),
    "Sad Pablo Escobar": (
        "sad_pablo", ["bored", "sad", "waiting", "nothing to do"],
        "Pablo Escobar looking sad with nothing to do. Use for having literally nothing to do or being bored.",
    ),
    "Shark Puppet": (
        "shark_puppet", ["shark", "jealous", "side eye", "suspicious"],
        "Little shark puppet looking suspicious. Use for jealousy or suspicious side-eyeing.",
    ),
}


def fetch_imgflip_memes() -> list[dict]:
    print("Fetching meme list from Imgflip API (top 100 templates)...")
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


def auto_tags(name: str) -> list[str]:
    """Generate basic tags from a display name when we don't have curated ones."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return [w for w in words if len(w) > 2][:6]


def main() -> None:
    init_chroma()
    imgflip_memes = fetch_imgflip_memes()
    print(f"Found {len(imgflip_memes)} templates from Imgflip.\n")

    seeded = 0
    skipped = 0

    for meme in imgflip_memes:
        display_name: str = meme["name"]
        url: str = meme["url"]

        # Use curated metadata if available, otherwise auto-generate
        if display_name in TEMPLATE_CATALOG:
            template_id, tags, description = TEMPLATE_CATALOG[display_name]
        else:
            template_id = slugify(display_name)
            tags = auto_tags(display_name)
            description = f"{display_name} meme template. Use for comedic situations matching this format."

        ext = Path(url.split("?")[0]).suffix or ".jpg"
        dest = TEMPLATES_DIR / f"{template_id}{ext}"

        print(f"[{template_id}] {display_name}")
        ok = download_image(url, dest)
        if not ok:
            skipped += 1
            continue

        upsert_template(
            template_id=template_id,
            name=display_name,
            tags=tags,
            description=description,
        )
        print(f"  [ok] Seeded ChromaDB")
        seeded += 1

        time.sleep(0.05)  # polite to Imgflip

    print(f"\nDone. Seeded: {seeded}  |  Skipped: {skipped}")
    print(f"Templates saved to: {TEMPLATES_DIR.resolve()}")
    print("Start the backend: uvicorn main:app --reload")


if __name__ == "__main__":
    main()
