"""
LLM intent-routing layer — powered by a local Ollama model (zero cost).

Features:
  - Few-shot RAG: semantically similar examples retrieved from ChromaDB injected into prompt
  - avoid_templates: conversation memory prevents template repetition within a session
  - JSON normalization: handles 3 common LLM output format deviations
  - Retry with strict prompt + lower temperature on parse failure
  - Hard fallback: always returns a valid IntentResponse — never raises to the caller
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
from pydantic import ValidationError

from config import get_settings
from image_processing.template_configs import DEFAULT_BOX_DESCRIPTIONS, get_config
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids, query_similar_memes
from vector_db.examples_store import get_similar_examples

_FALLBACK_TEMPLATES = [
    "drake", "distracted_boyfriend", "this_is_fine", "change_my_mind",
    "expanding_brain", "two_buttons", "success_kid", "one_does_not_simply",
    "doge", "woman_yelling_at_cat", "surprised_pikachu", "grus_plan",
    "mocking_spongebob", "hide_the_pain_harold", "buff_doge_vs_cheems",
    "batman_slapping_robin", "drunk_friend_caught",
    # Indian templates
    "baburao", "raju_hera_pheri", "srk_ddlj", "dhoni_calm",
    "circuit_plan", "jethalal_panic", "alliswel", "mogambo_khush", "sholay_gabbar",
]

# Always included in every prompt regardless of RAG results
_CORE_TEMPLATE_IDS = [
    "drake", "distracted_boyfriend", "grus_plan", "woman_yelling_at_cat",
    "expanding_brain", "two_buttons", "surprised_pikachu",
    "hide_the_pain_harold", "this_is_fine", "mocking_spongebob",
    "change_my_mind", "batman_slapping_robin",
    "buff_doge_vs_cheems", "boardroom_meeting_suggestion",
    "epic_handshake", "evil_kermit", "panik_kalm_panik", "tuxedo_winnie_the_pooh",
]

USE_WHEN: dict[str, str] = {
    # --- Core templates (explicitly configured layouts) ---
    "drake":                   "Rejecting one option and strongly preferring another — comparison or upgrade",
    "distracted_boyfriend":    "Someone ignoring what they have to chase something new/tempting",
    "grus_plan":               "A plan that has an obvious flaw revealed on the last step",
    "woman_yelling_at_cat":    "Two-sided argument: someone raging vs calm unbothered response",
    "expanding_brain":         "Escalating takes from basic/dumb to absurdly galaxy-brained",
    "two_buttons":             "Agonizing between two equally tempting or equally bad choices",
    "always_has_been":         "Revealing a dark or ironic truth that was always the case",
    "batman_slapping_robin":   "Interrupting someone mid-sentence to correct them sharply",
    "buff_doge_vs_cheems":     "Comparing two EXTERNAL versions of the same thing — strong vs weak, past vs present, rested vs exhausted, 2am energy vs 9am regret; NOT for internal conscience/temptation conflicts",
    "surprised_pikachu":       "Shocked by the obvious, predictable consequences of your own actions",
    "left_exit_12":            "Abandoning the sensible planned path to swerve toward something tempting",
    "change_my_mind":          "Stating ONE bold controversial opinion and daring anyone to argue — NOT for vocabulary upgrades, NOT for inner-demon conflicts; only for genuinely debatable claims",
    "anakin_padme":            "Assuming a positive outcome that clearly isn't happening — silent confirmation",
    "doge":                    "Wow, much, very, many — comically enthusiastic amazement or ironic enthusiasm",
    "galaxy_brain":            "Increasingly absurd logic chain that arrives at a wild conclusion",
    # --- Standard top/bottom single-panel templates ---
    "this_is_fine":            "Denial mode — sitting in literal chaos or disaster and refusing to acknowledge it; only fill 'situation' box describing the chaos — 'this is fine' is already printed in the image; NOT for happy discoveries or good news",
    "boardroom_meeting_suggestion": "An idea gets suggested and everyone piles on with the same bad take — boss throws them all out; use for repeated bad suggestions, groupthink, or ideas that always get shot down",
    "success_kid":             "Celebrating a small, unexpected, or petty win with a fist pump",
    "one_does_not_simply":     "Pointing out that something people think is easy is actually very hard",
    "mocking_spongebob":       "Mockingly repeating what someone said in alternating caps to show it's dumb",
    "hide_the_pain_harold":    "Smiling through obvious pain while projecting a fine public face — inner suffering vs outer performance; great for pretending to understand something you don't",
    "futurama_fry":            "Squinting with suspicion — not sure if X is real or just another stupid thing",
    "the_most_interesting_man": "A refined statement about something you simply never do — for grandiose declarations",
    "y_u_no":                  "Demanding to know why someone doesn't just do the obvious thing already",
    "ancient_aliens":          "Blaming aliens or a conspiracy for something with a perfectly ordinary explanation",
    "first_world_problems":    "Dramatically suffering over a trivial first-world inconvenience while crying",
    "bad_luck_brian":          "A person whose every attempt backfires spectacularly — worst case scenario every time",
    "good_guy_greg":           "Someone being unexpectedly considerate and wholesome when they don't have to be",
    "scumbag_steve":           "Someone acting obnoxious, selfish, or socially unaware in a painfully familiar way",
    "grumpy_cat":              "Categorical absolute refusal or negativity — 'No.' to literally everything",
    "philosoraptor":           "A deep philosophical question that sounds absurd but is surprisingly hard to answer",
    "bernie_sanders":          "Bernie sitting stoically with mittens — for cozy, unbothered, or deadpan observations",
    "stonks":                  "Making a terrible decision that somehow looks profitable on paper — absurd business logic",
    "crying_cat":              "Genuine despair or sadness, possibly over something trivial",
    "rollsafe":                "Using clever but flawed logic to avoid a problem — 'can't X if you never Y'",
    "disaster_girl":           "Watching chaos unfold with a satisfied smirk — enjoying someone else's downfall",
    "monkey_puppet":           "Awkwardly side-eyeing and looking away when something uncomfortable is said",
    "arthur_fist":             "Clenching fist in barely-contained rage — about to completely lose it",
    "kermit_tea":              "Passive-aggressively observing something about others while claiming it's none of your business",
    "oprah":                   "Giving the same thing to absolutely everyone — wild generosity or unfair equal distribution",
    "jack_sparrow":            "Being genuinely perplexed by something that technically makes sense but really shouldn't",
    "giga_chad":               "Making an extremely confident take and refusing to elaborate, justify, or apologize",
    "crying_laughing":         "Something is so absurd that you're genuinely unsure whether to laugh or cry",
    "notice_me_senpai":        "Desperately wanting attention from someone who completely doesn't notice you",
    "my_brain_is_full":        "So overwhelmed with information that you can't absorb any more",
    "all_the_things":          "Enthusiastically deciding to do literally all the things at once",
    "confession_bear":         "Admitting something embarrassing, shameful, or guilty in a deadpan format",
    "third_world_skeptical":   "Raising an eyebrow at a claim that sounds too convenient or good to be true",
    "socially_awkward_penguin": "Being completely paralyzed by social anxiety in a perfectly normal situation",
    "bad_pun_dog":             "A dog grinning smugly after making an absolutely terrible pun — for wordplay",
    "sean_bean_lotr":          "Brace yourself — something is coming; or pointing out something inevitable",
    "10_guy":                  "An oblivious person making a surprisingly deep or dumb observation while clearly out of it",
    "college_liberal":         "An idealistic take on a social issue that sounds good on paper but misses reality",
    "overly_attached_girlfriend": "When someone is way too clingy, possessive, or intense in a relationship",
    "first_day_on_internet":   "Someone discovering an obviously old internet meme and sharing it like it's new",
    "grandma_finds_internet":  "An older person encountering technology or internet culture and being baffled",
    "harold_hide_pain":        "Smiling through obvious pain — same vibe as hide_the_pain_harold",
    "meme_man":                "Stonks-adjacent — making an extremely logical or completely unhinged observation",
    "chad":                    "Ultra-confident stance on something that would normally be controversial or nerdy",
    "virgin_vs_chad":          "Contrasting the insecure weak approach with the ultra-confident chad approach",
    "trade_offer":             "I receive X. You receive Y — for lopsided or ironic deal proposals",
    "they_are_the_same_picture": "Pointing out that two things people treat as different are actually identical",
    "wait_that_s_illegal":     "Realizing something you've been doing is technically not allowed",
    "i_was_told":              "Expecting one thing and getting something completely different",
    "uno_reverse":             "Turning someone's argument or action right back on them",
    "megamind":                "No one said you couldn't do the thing — technically correct loophole logic",
    "is_this_a_pigeon":        "Confidently misidentifying something obvious — labeling the wrong thing incorrectly",
    "ight_imma_head_out":      "Spongebob getting up to leave — when something awkward or bad happens and you just go",
    "drunk_friend_caught":     "Someone caught on camera with a dazed, confused, blackout-adjacent stare — 'wait what's happening'; perfect for drunk friend moments, being caught off guard, pretending to be sober, POV phone-in-face surprise, or general dissociation at a social event",

    # --- Full catalog — file-stem-matched keys so ChromaDB lookups resolve correctly ---
    "epic_handshake":          "Two rivals, enemies, or opposites shaking hands because they both agree on one specific thing — 'we hate each other but we both hate X'; enemies uniting; two sides with nothing in common suddenly agreeing; unexpected common ground between opponents",
    "evil_kermit":             "INTERNAL CONSCIENCE CONFLICT: your inner demon/dark side vs your responsible/good side — two voices inside your head arguing; 'me telling myself to do X' vs 'evil me saying do Y instead'; NOT for external comparisons",
    "tuxedo_winnie_the_pooh":  "Saying the exact same thing in fancy vs plain language — vocabulary or phrasing upgrade with zero meaning change; calling a drink a 'beverage', saying 'residence' for 'house', using pretentious synonyms; NOT for opinions or comparisons",
    "panik_kalm_panik":        "Panic → brief false calm → panic returns worse; a situation that seemed resolved then gets dramatically worse",
    "imagination_spongebob":   "SpongeBob making an air-quote rainbow — presenting a sarcastic, grandiose, or ironic label for something",
    "squidward_window":        "Squidward staring from behind a curtain — watching something from outside, uninvited, lurking with quiet envy or judgment",
    "sleeping_shaq":           "Shaq lying awake for one thing, immediately asleep to another — priorities; selective awareness; can't sleep except about X",
    "uno_draw_25_cards":       "Draw 25 cards rather than admit/do X — someone choosing the worse option just to avoid acknowledging the obvious thing",
    "leonardo_dicaprio_cheers": "Leo pointing with champagne — 'ah yes, that's the one'; smug satisfaction at spotting something specific; toasting an exact moment",
    "laughing_leo":            "Leo pointing and laughing — found it, caught it, this is the funny thing right here; pointing out something ridiculous",
    "all_my_homies_hate":      "Group unanimous rejection — 'all my homies hate X'; rallying collective disdain, everyone agrees this thing is bad",
    "spiderman_pointing_at_spiderman": "Two Spider-Men pointing at each other — two identical things accusing each other of being the imposter; mutual blame",
    "spider_man_triple":       "Three Spider-Men all pointing at each other — three versions of the same thing each claiming to be the original",
    "charlie_conspiracy_always_sunny_in_philidelphia": "Charlie conspiracy board — manic red-string-and-photos energy; 'I've connected everything'; unhinged pattern recognition",
    "american_chopper_argument": "Father-son shouting match across 5 panels — escalating argument where the same bad take keeps coming back; going in circles",
    "flex_tape":               "Phil Swift slapping tape — overkill dramatic fix; 'I said that I can repair this' with maximum confidence and minimum logic",
    "marked_safe_from":        "Facebook safety check — 'Marked safe from X today'; treating a minor inconvenience like a natural disaster",
    "clown_applying_makeup":   "Progressively becoming the clown — each panel = another step toward doing the dumb thing you swore you wouldn't; self-awareness too late",
    "running_away_balloon":    "Person chasing an escaping balloon — label the balloon with what you're desperately chasing; it keeps floating away",
    "absolute_cinema":         "Scorsese pointing — 'this is peak cinema/art/content'; reserved for something genuinely great or ironically overpraised as a masterpiece",
    "gus_fring_we_are_not_the_same": "'We are not the same' — calm, clinical distinction between yourself and someone inferior; composed superiority",
    "star_wars_yoda":          "Yoda wisdom format — inverted sentence structure for mock-profound advice; 'When X, Y you must'",
    "the_rock_driving":        "The Rock double-taking while driving — suddenly noticing something unexpected in the rear-view; surprise re-evaluation",
    "friendship_ended":        "'Friendship ended with X, now Y is my best friend' — publicly replacing one favourite thing/person/tool with another",
    "but_that_s_none_of_my_business": "Kermit sipping tea — passive-aggressively observing something about others while claiming it's none of your business",
    "finding_neverland":       "Audience weeping — collective emotional devastation; something hit so hard the whole crowd is crying (sincere or ironic)",
    "who_killed_hannibal":     "Two people pointing guns at each other — mutual accusation stalemate; both sides did it; nobody is innocent here",
    "scooby_doo_mask_reveal":  "Pulling off a villain mask — 'it was X all along'; unmasking a hidden identity, ulterior motive, or obvious culprit",
    "the_scroll_of_truth":     "Opening a scroll then throwing it away — confronted with an uncomfortable truth and immediately rejecting it",
    "sad_pablo":               "Pablo Escobar standing bored against a wall — waiting forever for something that isn't coming; extreme, patient, hopeless waiting",
    "three_headed_dragon":     "Three-headed dragon where all three heads agree — for labeling three separate groups that unexpectedly all believe the same thing",
    "they_don_t_know":         "Lone person at a party — 'They don't know I [secret]'; feeling secretly superior, different, or burdened while blending in",
    "y_all_got_any_more_of_that": "Dave Chappelle desperately asking for more — cannot get enough of X; needy, hooked, please give me more",
    "soldier_protecting_sleeping_child": "Soldier shielding a sleeping child — something fiercely protected from an encroaching threat; defending innocence",
    "pawn_stars_best_i_can_do": "Rick Harrison — 'best I can do is X'; the offer is always way less than expected; disappointing counter-offer",
    "waiting_skeleton":        "Skeleton still waiting in a chair — been waiting so long you've become a skeleton; something that will never arrive",
    "disappointed_black_guy":  "Pure, wordless disappointment face — no explanation needed; profound personal let-down; you knew this would happen",
    "inhaling_seagull":        "Seagull taking a huge breath before screaming — winding up to say something unhinged, chaotic, or way too honest",
    "domino_effect":           "Small domino knocking over increasingly giant ones — labeling a minor trigger that causes a massive cascading consequence",
    "bike_fall":               "Guy falling off bike because he was distracted — caused their own crash by looking away from what mattered",
    "bell_curve":              "Bell curve meme — low IQ and high IQ people agree on the extreme take, mid-curve crowd disagrees; galaxy-brain extremes converging",
    "is_this_butterfly":       "Anime character confidently misidentifying a butterfly — 'Is this X?' when it is clearly not X; confident wrong labeling",
    "bernie_i_am_once_again_asking_for_your_support": "Bernie in mittens — 'I am once again asking for X'; recurring humble deadpan request; asking for the same thing repeatedly",
    "bernie_sanders_once_again_asking": "Bernie in mittens — same as above; recurring deadpan request format",
    "two_paths":               "Road forking into two paths — person at a crossroads choosing between two options; which way",
    "no_yes":                  "Simple No / Yes split — clean binary choice; something firmly rejected vs something eagerly accepted",
    "types_of_headaches_meme": "Head diagram labeling different headaches — each area of pain labeled with a specific thing that causes it",
    "whe_i_m_in_a_competition_and_my_opponent_is": "Me vs opponent split — showing a mismatch in effort, skill, or preparation between you and the competition",
    "where_monkey":            "'Where monkey?' — confused searching; something expected to be there is suddenly missing; bewildered absence",
    "whisper_and_goosebumps":  "Someone whispering and causing goosebumps — that one phrase, lyric, or line that hits differently every time",
    "two_guys_on_a_bus":       "Two men leaning in conspiratorially — secret planning, whispering schemes; two people in quiet agreement",
    "x_x_everywhere":          "Buzz Lightyear — 'X, X everywhere'; once you notice it, it's inescapable; a pattern appearing everywhere",
    "you_guys_are_getting_paid": "Tobey Maguire surprised — 'you guys are getting paid?'; discovering everyone else was getting something you didn't know about",
    "a_train_hitting_a_school_bus": "Train about to hit a bus stuck on tracks — visible incoming disaster that cannot be stopped; brace for impact",
    "look_at_me":              "'Look at me. I am the captain now' — hostile takeover of a role or situation; asserting new dominance",
    "i_m_the_captain_now":     "'I am the captain now' — seizing control; someone new asserting ownership of what you were running",
    "i_bet_he_s_thinking_about_other_women": "Person smiling with visible thought bubble — revealing what someone is actually thinking about vs what they claim",
    "blank_nut_button":        "Person frantically pressing a big red button — compulsively doing X; cannot stop pressing; triggered every time",
    "george_bush_9_11":        "'And then the towers fell' — a date-stamped event that changed everything; before/after a defining moment",
    "0_days_without_lenny_simpsons": "Safety counter reset to 0 — '0 days without incident'; something went wrong again and the counter starts over",
    "trump_bill_signing":      "Person at desk dramatically signing — executive decision made; officially decreeing or approving something with theatrical gravity",
    "anime_girl_hiding_from_terminator": "Girl hiding behind a pole from Terminator — hiding from something dangerous that's actively hunting you",
    "bugs_bunny_communist":    "Bugs Bunny in a Soviet hat — 'allow me to introduce some communism'; ironic collectivist or chaotic-neutral solution",
    "say_the_line_bart_simpsons": "'Say the line, Bart!' — crowd demanding someone say their predictable catchphrase; performing on cue",
    "megamind_no_bitches":     "Megamind 'No bitches?' — shocked that someone has zero of a thing; 'no X?'; disbelieving that someone lacks the obvious thing",
    "megamind_peeking":        "Megamind peeking through a tiny window — looking in from outside; observing something you're not part of; excluded spectator",
    "roll_safe_think_about_it": "Man tapping temple — 'can't X if you never Y'; sounds clever but is actually terrible logic used to avoid a problem",
    "theyre_the_same_picture": "Pam from The Office holding up two photos — 'They're the same picture'; two things people distinguish are actually identical",
    "third_world_skeptical_kid": "Skeptical kid raising an eyebrow — deeply suspicious of a claim that sounds too convenient; side-eye at something implausible",
    "this_is_where_i_d_put_my_trophy_if_i_had_one": "Empty shelf or display case — 'This is where I'd put X, if I had one'; wanting something you've never managed to get",
    "aj_styles_undertaker":    "AJ Styles facing the Undertaker — legendary rivals meeting; unexpected confrontation between two giants from different worlds",
    "grant_gustin_over_grave": "Person cheerfully posing over their own grave — making peace with impending doom; surprisingly unbothered about a terrible outcome",
    "drake_blank":             "Drake approving/rejecting without labels — blank version for custom top/bottom rejection-then-preference comparisons",
    "trump_bill_signing":      "Someone signing a document with theatrical gravity — officially decreeing something; executive decision energy",
    "mother_ignoring_kid_drowning_in_a_pool": "Mother on phone ignoring drowning kid — completely absorbed in one thing while something urgent is happening right next to you",
    "scientist_myself":        "Norman Osborn 'I'm something of a scientist myself' — unexpected relate; claiming insider status in something you're really not an expert in",
    "empire_state_climbers":   "Two people having a side conversation while climbing the Empire State Building — unexpected tangent mid-crisis; chatting about random things during a high-stakes moment",
    "shut_up_and_take_my_money": "Fry from Futurama throwing money — 'shut up and take my money'; wanting something so badly you'd pay anything; instant must-have energy",
    "friendship_ended":        "'Friendship ended with X, now Y is my best friend' — publicly replacing a former favourite with a new one",
    "laughing_leo":            "Leo DiCaprio pointing and laughing — spotted the funny thing; 'this guy, look at this guy'",

    # --- Indian templates ---
    "baburao":          "Baburao Apte from Hera Pheri (Paresh Rawal) — delivering a confidently wrong or absurd solution with full conviction; jugaad gone wrong; 'bhai yeh kar na'; when someone proposes the dumbest possible fix as if it's genius",
    "raju_hera_pheri":  "Raju from Hera Pheri (Akshay Kumar) in his iconic colourful shirt — cool, stylish, acting unbothered; for desi swagger, 'main hoon na' energy, confidently stepping into a situation",
    "srk_ddlj":         "Shah Rukh Khan and Kajol in the DDLJ train climax — reaching for each other just in time; for 'just made it', last-minute reunions, barely catching something, or anything dramatically timed",
    "dhoni_calm":       "MS Dhoni's legendary calm face — completely unbothered under extreme pressure; 'keep calm and finish it off'; everyone else is panicking but you're in flow state; ice-cold composure",
    "circuit_plan":     "Circuit (Arshad Warsi) from Munna Bhai on the phone — scheming, confidently executing a dumb plan; 'bhai ek kaam karte hain'; jugaad energy; desi problem-solving with zero qualifications",
    "jethalal_panic":   "Jethalal from Taarak Mehta ka Ooltah Chashmah — 4-panel escalating shock and panic; 'Babita ji dekh legi' energy; dreading consequences; caught off guard with increasing horror",
    "alliswel":         "Aamir Khan 'All is well' 3-panel from 3 Idiots — fake reassurance as things collapse; convincing yourself and others it's fine; toxic positivity; chanting to ignore an obvious disaster",
    "mogambo_khush":    "Mogambo from Mr. India — 'Mogambo khush hua'; sinister villain satisfaction when your plan works; evil grin energy; when karma hits, when you were right all along, or when the enemy finally suffers",
    "sholay_gabbar":    "Gabbar Singh from Sholay with his revolver — 'Kitne aadmi the'; demanding accountability for failure; menacing interrogation energy; calling out someone who underperformed or got routed",
}


def _build_template_catalog(template_ids: list[str]) -> dict:
    """
    Compact format — w = when to use, b = list of box label names.
    Omitting full box descriptions saves ~50% tokens vs the verbose format.
    """
    catalog: dict[str, dict] = {}
    for tid in template_ids:
        config = get_config(tid)
        boxes = config.box_descriptions or DEFAULT_BOX_DESCRIPTIONS
        catalog[tid] = {
            "w": USE_WHEN.get(tid, "general meme with top and bottom text"),
            "b": list(boxes.keys()),
        }
    return catalog


def _normalize_llm_response(data: dict, known_ids: set[str]) -> dict:
    """
    Handle common LLM JSON format deviations:
    1. Already correct: {"template_id": "...", "texts": {...}}
    2. Wrapped by template_id: {"drake": {"texts": {...}, "reasoning": "..."}}
    3. Field name aliases: {"id": "...", "captions": {...}}
    """
    if "template_id" in data and "texts" in data:
        return data

    for key, value in data.items():
        if isinstance(value, dict) and "texts" in value:
            return {
                "template_id": key,
                "texts": value["texts"],
                "reasoning": value.get("reasoning", ""),
            }

    normalized: dict = {}
    for alias in ("template_id", "id", "meme_id", "template", "meme"):
        if alias in data:
            normalized["template_id"] = data[alias]
            break
    for alias in ("texts", "captions", "text_boxes", "boxes", "labels", "caption"):
        if alias in data:
            normalized["texts"] = data[alias]
            break
    if normalized.get("template_id") and normalized.get("texts"):
        normalized["reasoning"] = data.get("reasoning", data.get("reason", ""))
        return normalized

    return data


def _format_few_shot(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["Here are examples of how similar messages were handled:\n"]
    for ex in examples:
        lines.append(
            f'  User: "{ex["user_message"]}"\n'
            f'  → template_id: "{ex["template_id"]}", texts: {json.dumps(ex["texts"])}\n'
        )
    return "\n".join(lines) + "\n\n"


_SYSTEM_TEMPLATE = """\
You are MemeGPT. Pick the best meme template and write captions for the user's message.

Catalog format: each key is a template_id. "w" = when to use it. "b" = box label names \
(use these exact labels in your "texts" output).

{few_shot_block}{avoid_block}Templates:
{template_catalog}

Respond with ONLY valid JSON — no markdown, no explanation:
{{
  "template_id": "<id from catalog>",
  "texts": {{"<box_label>": "<caption>"}},
  "reasoning": "<one sentence why>"
}}

Rules: use only template_ids and box labels listed above; captions under 80 chars; be funny.\
"""

_RETRY_TEMPLATE = """\
You are a JSON API. The user said: "{user_message}"

Return ONLY this exact JSON, nothing else:
{{"template_id": "PICK_ONE", "texts": {{"BOX_LABEL": "CAPTION"}}, "reasoning": "WHY"}}

Available template_ids: {template_ids}

Output raw JSON only — no markdown, no explanation.\
"""


async def _call_ollama(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": 150},
    }
    try:
        base = settings.ollama_host.rstrip("/")
        response = await client.post(
            f"{base}/api/chat",
            json=payload,
            headers={"ngrok-skip-browser-warning": "true"},
            follow_redirects=True,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise httpx.ConnectError(
            f"Cannot reach Ollama at {settings.ollama_host}. Run: ollama serve"
        )
    return response.json()["message"]["content"].strip()


async def _call_groq(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Groq cloud inference — free tier, ~400 t/s, no GPU required."""
    for attempt in range(2):
        payload: dict = {
            "model": settings.groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        # Qwen 3.x thinking mode emits reasoning tokens before JSON, breaking the parser.
        # Disable it explicitly for any Qwen model on this endpoint.
        if "qwen" in settings.groq_model.lower():
            payload["reasoning_effort"] = "none"
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code == 429:
            # Rate limited — respect Groq's retry-after (cap at 30s so we don't stall forever)
            retry_after = int(response.headers.get("retry-after", "3"))
            await asyncio.sleep(min(retry_after, 8))
            continue
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    # Both attempts hit 429 — return empty so parse_intent falls through to hard fallback
    # rather than raising httpx.HTTPStatusError and bypassing the fallback entirely
    return ""


async def _call_llm(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Route to Groq (cloud) or Ollama (local) based on LLM_PROVIDER config."""
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return await _call_groq(client, settings, messages, temperature)
    return await _call_ollama(client, settings, messages, temperature)


def _strip_markdown(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    return raw.strip()


async def parse_intent(
    user_message: str,
    avoid_templates: list[str] | None = None,
) -> IntentResponse:
    """
    Route a user message to the best meme template + captions.

    avoid_templates: list of recently used template IDs in this conversation —
    injected into the prompt to prevent repetition.
    """
    settings = get_settings()

    # All known IDs (used for validation only — NOT sent wholesale to the LLM)
    all_ids = list_template_ids() or _FALLBACK_TEMPLATES
    known_id_set = set(all_ids)

    # RAG pre-filter: find the 8 most semantically relevant templates for this message
    rag_results = query_similar_memes(user_message, n_results=8)
    rag_ids = [r["id"] for r in rag_results if r.get("id") in known_id_set]

    # Core templates always come first (guaranteed in prompt); unique RAG extras appended after.
    # Cap at 25 — 70b handles ~25 compact JSON entries well within its context window.
    core_set = set(_CORE_TEMPLATE_IDS)
    extra_rag = [id for id in rag_ids if id not in core_set]
    prompt_ids = (_CORE_TEMPLATE_IDS + extra_rag)[:25]
    template_ids = prompt_ids  # used in retry prompt below
    catalog = _build_template_catalog(prompt_ids)

    examples = get_similar_examples(user_message, n_results=3)
    few_shot_block = _format_few_shot(examples)

    avoid_block = ""
    if avoid_templates:
        avoid_block = (
            f"IMPORTANT — DO NOT repeat these recently used templates: "
            f"{', '.join(avoid_templates)}. Pick something different and fresh.\n\n"
        )

    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2),
        few_shot_block=few_shot_block,
        avoid_block=avoid_block,
    )

    async with httpx.AsyncClient() as client:
        # Attempt 1 — rich prompt with few-shot + avoid block
        try:
            raw = await _call_llm(client, settings, [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ])
            raw = _strip_markdown(raw)
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            result = IntentResponse(**data)
            if result.template_id not in known_id_set:
                raise ValueError(f"Hallucinated template_id: {result.template_id}")
            return result
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError):
            pass

        # Attempt 2 — minimal strict prompt at low temperature
        retry_prompt = _RETRY_TEMPLATE.format(
            user_message=user_message,
            template_ids=", ".join(template_ids[:14]),
        )
        try:
            raw = await _call_llm(client, settings, [
                {"role": "user", "content": retry_prompt},
            ], temperature=0.2)
            raw = _strip_markdown(raw)
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            result = IntentResponse(**data)
            if result.template_id not in known_id_set:
                raise ValueError(f"Hallucinated template_id: {result.template_id}")
            return result
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError):
            pass

    # Hard fallback — always returns something rather than 500-ing
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={
            "top_text": user_message[:60] if len(user_message) <= 60 else user_message[:57] + "...",
            "bottom_text": "This is fine.",
        },
        reasoning="Fallback: model failed to produce valid JSON on both attempts",
    )
