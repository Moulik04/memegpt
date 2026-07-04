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
    "expanding_brain", "two_buttons", "one_does_not_simply",
    "woman_yelling_at_cat", "surprised_pikachu", "grus_plan",
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
    "drake":                   "SETTLED PREFERENCE: A verdict already reached — smugly reject option A, endorse option B; no agonizing, no conflict. NOT for undecided dilemmas (two_buttons), inner temptation (evil_kermit), two people arguing (woman_yelling_at_cat), or strong-vs-weak decay (buff_doge_vs_cheems).",
    "distracted_boyfriend":    "DISLOYAL WANDERING EYE: You already HAVE or committed to one thing, and you're openly checking out a shiny new thing while the committed thing watches — a three-label love triangle. NOT for abandoning a plan mid-journey (left_exit_12) and NOT for refusing a task (uno_draw_25_cards).",
    "grus_plan":               "SELF-AUTHORED PLAN BACKFIRE: Presenting YOUR OWN numbered plan and only noticing at the final panel that one step is a disaster — panel 4 repeats panel 3 verbatim with dawning horror. Requires an actual multi-step plan; NOT a two-person exchange (anakin_padme) and NOT an emotional sequence (panik_kalm_panik).",
    "woman_yelling_at_cat":    "SCREAMING VS DEADPAN ARGUMENT: Two DIFFERENT parties in an actual exchange — one hurls a furious emotional accusation, the other replies with a calm dismissive one-liner. Requires a back-and-forth; NOT a comparison (drake, buff_doge_vs_cheems) and NOT one person's inner conflict (evil_kermit).",
    "expanding_brain":         "ENLIGHTENMENT LADDER: FOUR independent, alternative approaches to the SAME problem, ranked from basic to ironically transcendent — often praising the dumbest method as genius. The levels are separate options, not a causal chain. NOT a 2-step rephrase (tuxedo_winnie_the_pooh).",
    "two_buttons":             "UNDECIDED SWEATY DILEMMA: Paralyzed between two mutually exclusive options with NO winner picked — the sweating indecision IS the joke. NOT for choices already made (drake), good-vs-evil conscience (evil_kermit), or two-party arguments (woman_yelling_at_cat).",
    "always_has_been":         "Revealing a dark or ironic truth that was always the case",
    "batman_slapping_robin":   "Interrupting someone mid-sentence to correct them sharply",
    "buff_doge_vs_cheems":     "STRONG-THEN VS WEAK-NOW: Third-person comparison of two EXTERNAL versions of the same thing — glorious/tough version vs pathetic/degraded version (past vs present, theirs vs ours). Nobody is choosing anything; NOT for preferences (drake), inner temptation (evil_kermit), or arguments (woman_yelling_at_cat).",
    "surprised_pikachu":       "Shocked by the obvious, predictable consequences of your own actions",
    "left_exit_12":            "LAST-SECOND SWERVE: Mid-journey, violently veering off the sensible planned ROUTE toward a tempting exit — the joke is the sudden reckless course-change in motion. The abandoned thing is a plan or intention, not a partner or possession (that's distracted_boyfriend); NOT pure task-avoidance (uno_draw_25_cards).",
    "change_my_mind":          "DEBATE-ME SIGN: ONE bold, genuinely debatable opinion stated flatly as fact, daring the world to argue. Single statement, no progression, no rephrasing; NOT for fancy synonyms (tuxedo_winnie_the_pooh) or multi-step reasoning (expanding_brain).",
    "anakin_padme":            "UNANSWERED '...RIGHT?': A two-speaker dialogue — one states something, the other optimistically assumes the good interpretation ('...right?') and is met with dead silence. Requires an assumption left hanging between two parties; NOT your own plan failing (grus_plan) and NOT solo panic beats (panik_kalm_panik).",
    # --- Standard top/bottom single-panel templates ---
    "this_is_fine":            "Denial mode — sitting in literal chaos or disaster and refusing to acknowledge it; only fill 'situation' box describing the chaos — 'this is fine' is already printed in the image; NOT for happy discoveries or good news",
    "boardroom_meeting_suggestion": "An idea gets suggested and everyone piles on with the same bad take — boss throws them all out; use for repeated bad suggestions, groupthink, or ideas that always get shot down",
    "one_does_not_simply":     "Pointing out that something people think is easy is actually very hard",
    "mocking_spongebob":       "Mockingly repeating what someone said in alternating caps to show it's dumb",
    "hide_the_pain_harold":    "Smiling through obvious pain while projecting a fine public face — inner suffering vs outer performance; great for pretending to understand something you don't",
    "futurama_fry":            "Squinting with suspicion — not sure if X is real or just another stupid thing",
    "ancient_aliens":          "Blaming aliens or a conspiracy for something with a perfectly ordinary explanation",
    "disaster_girl":           "Watching chaos unfold with a satisfied smirk — enjoying someone else's downfall",
    "monkey_puppet":           "Awkwardly side-eyeing and looking away when something uncomfortable is said",
    "oprah":                   "Giving the same thing to absolutely everyone — wild generosity or unfair equal distribution",
    "grandma_finds_the_internet": "An older person encountering technology or internet culture and being baffled",
    "trade_offer":             "I receive X. You receive Y — for lopsided or ironic deal proposals",
    "is_this_a_pigeon":        "Confidently misidentifying something obvious — labeling the wrong thing incorrectly",
    "drunk_friend_caught":     "Someone caught on camera with a dazed, confused, blackout-adjacent stare — 'wait what's happening'; perfect for drunk friend moments, being caught off guard, pretending to be sober, POV phone-in-face surprise, or general dissociation at a social event",

    # --- Full catalog — file-stem-matched keys so ChromaDB lookups resolve correctly ---
    "epic_handshake":          "Two rivals, enemies, or opposites shaking hands because they both agree on one specific thing — 'we hate each other but we both hate X'; enemies uniting; two sides with nothing in common suddenly agreeing; unexpected common ground between opponents",
    "evil_kermit":             "INNER DEVIL DIALOGUE: One person, two inner voices — sensible self says the responsible thing, hooded dark self whispers the irresponsible temptation ('me:' vs 'also me:'). NOT for comparing external things (drake, buff_doge_vs_cheems), rational 50/50 choices (two_buttons), or two different people in conflict (woman_yelling_at_cat).",
    "tuxedo_winnie_the_pooh":  "VOCABULARY UPGRADE: The exact same statement said twice — plain wording, then a needlessly fancy rephrasing with ZERO change in meaning. Exactly 2 levels; NOT a 4-step escalation (expanding_brain) and NOT an actual opinion or claim (change_my_mind).",
    "panik_kalm_panik":        "PANIC WHIPLASH: Three emotional beats in sequence — alarming thing, then a reassuring detail that calms you, then a realization that makes it WORSE than before. About one person's feelings over time; NOT a numbered plan (grus_plan) and NOT a dialogue with dashed assumptions (anakin_padme).",
    "imagination_spongebob":   "SpongeBob making an air-quote rainbow — presenting a sarcastic, grandiose, or ironic label for something",
    "squidward_window":        "Squidward staring from behind a curtain — watching something from outside, uninvited, lurking with quiet envy or judgment",
    "sleeping_shaq":           "Shaq lying awake for one thing, immediately asleep to another — priorities; selective awareness; can't sleep except about X",
    "uno_draw_25_cards":       "AVOIDANCE AT ABSURD COST: Offered one small reasonable action ('just do/say/admit X') and choosing a massive self-inflicted penalty instead. Pure refusal — there is NO tempting alternative being chased, which is what separates it from distracted_boyfriend and left_exit_12.",
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
    "mother_ignoring_kid_drowning_in_a_pool": "Mother on phone ignoring drowning kid — completely absorbed in one thing while something urgent is happening right next to you",
    "scientist_myself":        "Norman Osborn 'I'm something of a scientist myself' — unexpected relate; claiming insider status in something you're really not an expert in",
    "empire_state_climbers":   "Two people having a side conversation while climbing the Empire State Building — unexpected tangent mid-crisis; chatting about random things during a high-stakes moment",
    "shut_up_and_take_my_money": "Fry from Futurama throwing money — 'shut up and take my money'; wanting something so badly you'd pay anything; instant must-have energy",

    # --- New 2024-2026 templates ---
    "chill_guy":                "UNBOTHERED PROTAGONIST: Responding to stress, chaos, or high expectations by simply not caring — 'just a chill guy who lowkey doesn't gaf.' The nonchalance IS the punchline; NOT for hiding pain behind a smile (hide_the_pain_harold) or denial amid literal disaster (this_is_fine).",
    "mr_incredible_uncanny":    "VIBE DETERIORATION 2-PANEL: The same person before vs after learning or experiencing something horrifying — normal face labeled with the fine situation, cursed distorted face labeled with the nightmare version. NOT a strength/quality comparison of external things (buff_doge_vs_cheems) and NOT a three-beat panic sequence (panik_kalm_panik).",
    "midwit_bell_curve":        "HORSESHOE WISDOM: The simpleton (left) and the enlightened sage (right) say the SAME simple thing, while the anxious midwit in the middle overcomplicates it. Requires the two extremes agreeing against the middle; NOT a ranked worst-to-best ladder (expanding_brain).",
    "math_lady":                "FRANTIC MENTAL MATH: Actively trying to calculate, decode, or figure something out in real time while visibly lost — floating equations energy. For effortful live confusion; NOT skeptical squinting at a claim (futurama_fry) and NOT information overload shutdown (my_brain_is_full).",
    "kiss_cam_caught":          "BUSTED ON THE JUMBOTRON: Two things or people caught together in the most public way possible, mid-flinch, trying to hide too late. For exposed secrets, guilty pairings, and incompatible things discovered together; NOT for general embarrassment or solo awkwardness (monkey_puppet).",
    "turkish_shooter":          "EFFORTLESS PRO: Casually achieving with zero equipment, prep, or visible effort what everyone else needs full gear and sweat for — hand-in-pocket mastery. For minimal-effort excellence and 'built different' calm; NOT for confident hot takes (giga_chad) or petty wins (success_kid).",
    "well_yes_but_actually_no": "TECHNICALLY-TRUE REVERSAL: Something that is technically correct yet completely wrong in practice or spirit — the baked-in 'Well yes, but actually no' is the answer. Only fill the claim being answered; NOT for loophole logic you're endorsing (megamind) or corrections mid-sentence (batman_slapping_robin).",
    "ah_shit_here_we_go_again": "DREADED RERUN: A familiar bad situation starting over yet again, met with weary resignation instead of shock — you have been here before and you know exactly how this ends. NOT for first-time consequences (surprised_pikachu) and NOT for escalating panic (panik_kalm_panik).",
    "sad_hamster":              "PATHETIC PLEADING EYES: Feeling small, rejected, or pitiful and milking it for sympathy — theatrical puppy-dog-eyes self-pity over something minor. For cute performative sadness; NOT genuine despair (crying_cat) and NOT dramatic trivial suffering played straight (first_world_problems).",

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
