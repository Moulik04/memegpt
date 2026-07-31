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

import httpx
from pydantic import ValidationError

from config import get_settings
from image_processing.template_configs import DEFAULT_BOX_DESCRIPTIONS, get_config
from nlp.llm_client import call_llm, strip_markdown
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
    "always_has_been":         "IRONIC 'IT ALWAYS WAS': Revealing that a surprising or dark truth was secretly true the entire time, recontextualizing everything that came before. E.g. realizing the 'random' outage was actually planned maintenance nobody announced. A single flat reveal, not a gradual escalation.",
    "batman_slapping_robin":   "SHARP MID-SENTENCE CORRECTION: Interrupting someone before they finish, cutting them off hard to correct or contradict what they're saying — the interruption itself is forceful, not gentle. E.g. cutting off a teammate mid-explanation because their approach is wrong. NOT for a slow technically-true-but-wrong reveal (well_yes_but_actually_no).",
    "buff_doge_vs_cheems":     "STRONG-THEN VS WEAK-NOW: Third-person comparison of two EXTERNAL versions of the same thing — glorious/tough version vs pathetic/degraded version (past vs present, theirs vs ours). Nobody is choosing anything; NOT for preferences (drake), inner temptation (evil_kermit), or arguments (woman_yelling_at_cat).",
    "surprised_pikachu":       "SHOCKED BY YOUR OWN OBVIOUS CONSEQUENCES: Wide-eyed surprise at an outcome that was completely predictable given your own actions — the shock is the joke, since anyone else could see it coming. E.g. shocked that skipping tests broke production. NOT someone else's disappointing counter-offer (pawn_stars_best_i_can_do).",
    "left_exit_12":            "LAST-SECOND SWERVE: Mid-journey, violently veering off the sensible planned ROUTE toward a tempting exit — the joke is the sudden reckless course-change in motion. The abandoned thing is a plan or intention, not a partner or possession (that's distracted_boyfriend); NOT pure task-avoidance (uno_draw_25_cards).",
    "change_my_mind":          "DEBATE-ME SIGN: ONE bold, genuinely debatable opinion stated flatly as fact, daring the world to argue. Single statement, no progression, no rephrasing; NOT for fancy synonyms (tuxedo_winnie_the_pooh) or multi-step reasoning (expanding_brain).",
    "anakin_padme":            "UNANSWERED '...RIGHT?': A two-speaker dialogue — one states something, the other optimistically assumes the good interpretation ('...right?') and is met with dead silence. Requires an assumption left hanging between two parties; NOT your own plan failing (grus_plan) and NOT solo panic beats (panik_kalm_panik).",
    # --- Standard top/bottom single-panel templates ---
    "this_is_fine":            "Denial mode — sitting in literal chaos or disaster and refusing to acknowledge it; only fill 'situation' box describing the chaos — 'this is fine' is already printed in the image; NOT for happy discoveries or good news",
    "boardroom_meeting_suggestion": "GROUP PILE-ON, IDEA REJECTED: An idea gets suggested in a meeting, everyone in the room enthusiastically piles onto the SAME bad take, then it gets thrown out. E.g. a team all agreeing on a risky shortcut before the boss shuts it down. Requires a group unanimously agreeing on one idea that then fails; NOT a two-sided circular argument (american_chopper_argument).",
    "one_does_not_simply":     "SECRETLY HARD TASK: Declaring that something everyone assumes is easy is actually very difficult — a solemn, mock-epic warning. E.g. 'one does not simply merge without a code review,' or 'one does not simply skip leg day.' A single declarative statement, not a comparison or dialogue.",
    "mocking_spongebob":       "MOCKING ALTERNATING-CAPS REPETITION: Repeating someone's exact words back at them in aLtErNaTiNg CaPs to mock how dumb or entitled they sound. Must quote the person's own words; NOT for watching someone's downfall in silence (disaster_girl) and NOT a sharp interrupting correction (batman_slapping_robin).",
    "hide_the_pain_harold":    "SMILING THROUGH IT: A forced, pained smile projecting 'everything's fine' while quietly suffering or faking understanding underneath. E.g. nodding along in a meeting you don't understand. NOT genuinely not caring at all (chill_guy).",
    "futurama_fry":            "SUSPICIOUS SQUINT: Narrowed eyes, not quite convinced — wondering if something is genuinely real or just another dumb thing pretending to be legitimate. E.g. squinting at a 'limited time' sale that's been running for months. NOT actively working through a problem (math_lady).",
    "ancient_aliens":          "BLAME THE CONSPIRACY: Reaching for an absurd conspiracy-theory explanation for something that has a totally mundane, obvious cause. E.g. blaming Mercury retrograde for a bad Wi-Fi day. NOT a genuine unhinged pattern-connecting spiral (charlie_conspiracy_always_sunny_in_philidelphia).",
    "disaster_girl":           "SMUG SATISFACTION AT SOMEONE ELSE'S DOWNFALL: A quiet, satisfied smirk while chaos unfolds around or because of someone else — not gloating out loud, not mocking their words, just enjoying the moment. E.g. watching a rival's presentation crash after they dismissed your warning. NOT mockingly repeating someone's own words back at them (mocking_spongebob).",
    "monkey_puppet":           "AWKWARD SIDE-EYE: Silently glancing away, unsure how to react to something uncomfortable just said or done — the awkwardness IS the joke, no words needed. E.g. the room going quiet after an inappropriate joke.",
    "oprah":                   "EVERYBODY GETS ONE: 'You get an X! You get an X!' — distributing the same thing to literally everyone in the room, generous or absurdly indiscriminate. E.g. every team getting blamed equally for one person's mistake.",
    "grandma_finds_the_internet": "OUT-OF-TOUCH DIGITAL CONFUSION: An older or out-of-touch person encountering modern tech or internet culture and being completely baffled by it. E.g. a relative replying-all to a group chat by accident.",
    "trade_offer":             "LOPSIDED TRADE PROPOSAL: 'I receive X. You receive Y.' — a flatly stated, wildly unbalanced trade, presented as if it's a fair deal. E.g. 'I receive credit for the project. You receive the 2am debugging session.' Ironic or one-sided exchanges.",
    "is_this_a_pigeon":        "CONFIDENT WRONG LABEL: Pointing at something and confidently, earnestly misidentifying it as something else entirely. E.g. calling a routine bug fix a 'major feature,' or mistaking a rerun for new content. NOT a claimed-identical comparison of two real things (theyre_the_same_picture).",
    "drunk_friend_caught":     "Someone caught on camera with a dazed, confused, blackout-adjacent stare — 'wait what's happening'; perfect for drunk friend moments, being caught off guard, pretending to be sober, POV phone-in-face surprise, or general dissociation at a social event",

    # --- Full catalog — file-stem-matched keys so ChromaDB lookups resolve correctly ---
    "epic_handshake":          "UNLIKELY COMMON GROUND: Two rivals, enemies, or opposites shaking hands because they discover they agree on exactly one specific thing, despite disliking everything else about each other. E.g. two feuding coworkers bonding over hating the same broken tool.",
    "evil_kermit":             "INNER DEVIL DIALOGUE: One person, two inner voices — sensible self says the responsible thing, hooded dark self whispers the irresponsible temptation ('me:' vs 'also me:'). NOT for comparing external things (drake, buff_doge_vs_cheems), rational 50/50 choices (two_buttons), or two different people in conflict (woman_yelling_at_cat).",
    "tuxedo_winnie_the_pooh":  "VOCABULARY UPGRADE: The exact same statement said twice — plain wording, then a needlessly fancy rephrasing with ZERO change in meaning. Exactly 2 levels; NOT a 4-step escalation (expanding_brain) and NOT an actual opinion or claim (change_my_mind).",
    "panik_kalm_panik":        "PANIC WHIPLASH: Three emotional beats in sequence — alarming thing, then a reassuring detail that calms you, then a realization that makes it WORSE than before. About one person's feelings over time; NOT a numbered plan (grus_plan) and NOT a dialogue with dashed assumptions (anakin_padme).",
    "imagination_spongebob":   "SARCASTIC AIR-QUOTE LABEL: Presenting something with a mocking, grandiose, or ironic title via an imaginary rainbow — the label itself is the joke. E.g. imagining 'the perfect candidate' for a role that doesn't exist.",
    "squidward_window":        "LURKING ENVIOUS OUTSIDER: Watching something enviously or judgmentally from behind a curtain or window — uninvited, quietly resentful, not part of it. E.g. watching a coworker's project get praised while yours goes unnoticed. NOT excited/neutral observation from outside (megamind_peeking) — this is specifically envy or judgment.",
    "sleeping_shaq":           "SELECTIVE INSOMNIA: Wide awake and unable to sleep about one specific thing, yet completely unbothered (or instantly asleep) about something objectively more important. E.g. losing sleep over a typo in a Slack message but sleeping fine before a huge presentation.",
    "uno_draw_25_cards":       "AVOIDANCE AT ABSURD COST: Offered one small reasonable action ('just do/say/admit X') and choosing a massive self-inflicted penalty instead. Pure refusal — there is NO tempting alternative being chased, which is what separates it from distracted_boyfriend and left_exit_12.",
    "leonardo_dicaprio_cheers": "LEO'S SATISFIED TOAST: Raising a glass while pointing — savoring the exact moment you spotted, achieved, or nailed something, mid-celebration; smug satisfaction, not mockery. E.g. clocking a plot twist coming from a mile away. NOT laughing at something ridiculous (laughing_leo).",
    "laughing_leo":            "LEO POINTING AND LAUGHING: Spotted something absurd and can't stop laughing while pointing at it — mockery or delighted disbelief, not quiet satisfaction. E.g. catching a typo in a company-wide email. NOT a smug toast at a well-earned moment (leonardo_dicaprio_cheers).",
    "all_my_homies_hate":      "UNANIMOUS GROUP DISDAIN: 'All my homies hate X' — a flat rallying cry declaring collective, unanimous rejection of one specific thing. E.g. 'all my homies hate daylight saving time,' or 'all my homies hate surprise meetings.'",
    "spiderman_pointing_at_spiderman": "TWO-WAY MUTUAL BLAME: Exactly two identical or interchangeable things or people, each accusing the other of being the fake, the problem, or the imposter. E.g. two coworkers each blaming the other for a missed deadline. NOT for three parties (spider_man_triple) and NOT an armed two-person stalemate (who_killed_hannibal).",
    "spider_man_triple":       "THREE-WAY MUTUAL BLAME: Three separate versions of the same thing, each pointing at the other two and claiming to be the real one. E.g. three friends all insisting they had the original idea. Requires exactly three; NOT the classic two-way version (spiderman_pointing_at_spiderman).",
    "charlie_conspiracy_always_sunny_in_philidelphia": "UNHINGED CONSPIRACY BOARD: Manic red-string-and-photos energy — frantically connecting unrelated dots into an elaborate, over-the-top theory. E.g. 'proving' a coworker's rise through the company was all planned from day one. NOT a single flat mundane-explanation joke (ancient_aliens) — this is the full unhinged spiral.",
    "american_chopper_argument": "CIRCULAR SHOUTING MATCH: A back-and-forth argument across multiple panels where the same point keeps getting shouted again and again, neither side backing down — going in circles, not a group pile-on. E.g. an argument that keeps circling back to the same unresolved point in a group chat. NOT a group unanimously piling on ONE bad idea (boardroom_meeting_suggestion).",
    "flex_tape":               "OVERKILL DUCT-TAPE FIX: A wildly overconfident, disproportionate fix applied to a problem — maximum bravado, minimum actual engineering. E.g. duct-taping over a production bug instead of fixing the root cause.",
    "marked_safe_from":        "TREATING A MINOR THING LIKE A DISASTER: 'Marked safe from X' — using disaster-level language for a trivial inconvenience, played completely straight. E.g. 'marked safe from Monday's stand-up meeting,' or 'marked safe from the office coffee machine breaking again.'",
    "clown_applying_makeup":   "BECOMING THE CLOWN STEP BY STEP: Each panel is another step toward doing the exact dumb thing you swore you wouldn't — self-awareness arriving too late to stop it. E.g. swearing you won't check work email on vacation, then slowly doing exactly that, panel by panel. NOT a bad situation simply repeating without escalation (ah_shit_here_we_go_again).",
    "running_away_balloon":    "CHASING THE THING THAT KEEPS ESCAPING: Desperately chasing after something that keeps floating just out of reach — label the balloon with what you're chasing. E.g. chasing 'work-life balance,' or chasing a promotion that keeps getting pushed back.",
    "absolute_cinema":         "PEAK [THING], SERIOUSLY OR IRONICALLY: Declaring something 'this is peak cinema' — either genuinely impressive or ironically overhyped for something mundane. E.g. calling a beautifully organized spreadsheet 'peak cinema,' or genuinely praising a great piece of work this way.",
    "gus_fring_we_are_not_the_same": "CALM SUPERIORITY: 'We are not the same' — a composed, clinical, almost polite way of pointing out you're fundamentally better than someone else. E.g. calmly distinguishing your approach from a sloppier competitor's, without raising your voice. NOT a mocking repetition of someone's own words (mocking_spongebob) — this is quiet, not loud.",
    "star_wars_yoda":          "INVERTED MOCK-WISDOM: Yoda's backwards sentence structure used for mock-profound, exaggeratedly wise-sounding advice. E.g. 'Deploy on Friday, you must not,' or 'Debug it myself, I will.'",
    "the_rock_driving":        "SUDDEN REAR-VIEW DOUBLE-TAKE: Casually driving along, then suddenly noticing something unexpected behind you and doing a surprised double-take. E.g. suddenly realizing a forgotten task is due today.",
    "friendship_ended":        "PUBLIC REPLACEMENT ANNOUNCEMENT: 'Friendship ended with X, now Y is my best friend' — a flat, deadpan declaration that you've swapped one favorite thing, tool, or person for another. Exactly one old thing, one new thing, no ranking or escalation. E.g. switching code editors after years of loyalty. NOT a ranked ladder of increasingly better options (expanding_brain).",
    "but_that_s_none_of_my_business": "PASSIVE-AGGRESSIVE TEA-SIPPING OBSERVATION: Kermit sipping tea while pointedly observing something about someone else, then disclaiming involvement — 'but that's none of my business.' E.g. quietly noting a coworker takes credit for others' work, then pointedly saying nothing further.",
    "finding_neverland":       "COLLECTIVE TEARFUL DEVASTATION: An entire audience or group reduced to tears together — something hit so hard everyone's crying, sincerely or dramatically overplayed. E.g. the whole team getting emotional at a heartfelt goodbye message.",
    "who_killed_hannibal":     "ARMED MUTUAL STANDOFF: Two people pointing guns at each other — a tense stalemate where both sides are equally implicated and neither will back down. E.g. two departments each blaming the other for a shared failure, neither willing to admit fault. NOT an unarmed two-way blame exchange (spiderman_pointing_at_spiderman) — this carries real tension and stakes.",
    "scooby_doo_mask_reveal":  "UNMASKING THE CULPRIT: Pulling off a villain's mask to reveal who was behind it all along — a specific hidden identity gets exposed. E.g. discovering which coworker has been taking credit for your work. NOT confronting an abstract uncomfortable truth (the_scroll_of_truth).",
    "the_scroll_of_truth":     "REJECTING AN UNCOMFORTABLE TRUTH: Opening a scroll, reading a truth about yourself or the situation, then immediately throwing it away in denial. E.g. reading your own bad code review feedback. An abstract truth, not a specific hidden person; NOT unmasking a culprit (scooby_doo_mask_reveal).",
    "sad_pablo":               "BORED, ENDLESS, HOPELESS WAITING: Standing around for something that clearly isn't coming — resigned, deflated patience, not comedic exaggeration. E.g. waiting for a reply that's never coming. NOT the literal 'waited until I died' skeleton bit (waiting_skeleton).",
    "three_headed_dragon":     "THREE UNEXPECTED ALLIES: A three-headed dragon where all three heads unexpectedly agree — for labeling three separate groups who unexpectedly share the exact same belief. E.g. three completely different departments all secretly agreeing the new policy is bad.",
    "they_don_t_know":         "SECRETLY DIFFERENT AT THE PARTY: Standing in a crowd while internally noting 'they don't know I [secret]' — feeling quietly superior, burdened, or different while blending in. E.g. attending a meeting while secretly already knowing the outcome.",
    "y_all_got_any_more_of_that": "DESPERATE FOR MORE: Wide-eyed, can't-get-enough desperation for more of something — needy, hooked, please-give-me-more energy. E.g. desperately wanting more of a great song on repeat.",
    "soldier_protecting_sleeping_child": "FIERCELY GUARDING SOMETHING VULNERABLE: A soldier shielding a sleeping child from an approaching threat — protecting something innocent or vulnerable from encroaching danger. E.g. protecting a junior teammate from unfair blame.",
    "pawn_stars_best_i_can_do": "DISAPPOINTING LOWBALL COUNTER-OFFER: 'Best I can do is X' — a flat, unbothered counter that's way less than what was hoped for or asked. Requires an actual back-and-forth negotiation or ask; NOT shock at an unexpected consequence (surprised_pikachu) — this is a deliberate, calm lowball, not a surprised reaction.",
    "waiting_skeleton":        "WAITED UNTIL DEATH: So long spent waiting that you've literally become a skeleton — the wait itself is the entire joke, comedic and exaggerated. E.g. waiting on a PR review. NOT quiet resigned patience without the death imagery (sad_pablo).",
    "disappointed_black_guy":  "WORDLESS PROFOUND DISAPPOINTMENT: A flat, silent, deeply knowing disappointment — no explanation needed, you saw this coming and it still hurts. E.g. the look after a promised feature ships broken again.",
    "inhaling_seagull":        "WINDING UP TO SAY SOMETHING UNHINGED: Taking a huge, dramatic breath before unleashing something chaotic, too honest, or completely unfiltered. E.g. the deep breath before finally telling a coworker what you really think.",
    "domino_effect":           "SMALL TRIGGER, HUGE CASCADE: A tiny domino knocking over an increasingly giant chain reaction — label the small cause and the disproportionate consequence. E.g. one typo in a config file taking down a whole production system. NOT a single person's own inattention causing their own crash (bike_fall).",
    "bike_fall":               "SELF-INFLICTED CRASH FROM DISTRACTION: Someone crashes because they were staring at something else instead of paying attention — one person, one cause, one consequence. E.g. walking into a pole while looking at your phone. NOT a cascading multi-step chain reaction (domino_effect).",
    "bernie_sanders_once_again_asking": "RECURRING HUMBLE DEADPAN ASK: Bernie in mittens — 'I am once again asking for X' — a tired, deadpan repeat of the exact same request, asked with weary patience rather than anger. E.g. once again asking teammates to write tests.",
    "two_paths":               "CROSSROADS DECISION: A literal fork in the road — standing at a crossroads deciding between two real, distinct paths forward. E.g. choosing between two competing project approaches. NOT the sweaty paralysis of two_buttons — this is calmer, more deliberate.",
    "no_yes":                  "CLEAN BINARY SPLIT: A simple No/Yes contrast — one thing firmly rejected, another eagerly accepted, side by side. E.g. 'No to Monday meetings. Yes to Friday deploys.'",
    "types_of_headaches_meme": "LABELED PAIN DIAGRAM: A head diagram labeling different areas of pain, each tied to a specific cause. E.g. labeling different kinds of work stress by where they 'hurt' — deadline pressure, scope creep, surprise meetings.",
    "whe_i_m_in_a_competition_and_my_opponent_is": "EFFORT MISMATCH VS COMPETITION: A side-by-side showing a huge gap in effort, skill, or preparation between you and whoever you're up against. E.g. showing up with a rough draft against a competitor's polished pitch.",
    "where_monkey":            "'WHERE MONKEY?': Confused, urgent searching for something that was expected to be there and is suddenly, bewilderingly missing. E.g. searching for a file that was definitely saved.",
    "whisper_and_goosebumps":  "THAT LINE THAT HITS EVERY TIME: Someone whispering a specific phrase or lyric that gives goosebumps — the one line that never stops landing. E.g. the specific phrase in a song.",
    "two_guys_on_a_bus":       "QUIET CONSPIRATORIAL PLANNING: Two people leaning in together, whispering — secret scheming or quiet mutual agreement away from everyone else. E.g. two coworkers quietly agreeing to push back on a bad decision together.",
    "x_x_everywhere":          "ONCE YOU SEE IT, YOU CAN'T UNSEE IT: Buzz Lightyear — 'X, X everywhere' — noticing a pattern that then seems to appear inescapably everywhere. E.g. noticing one typo and then seeing typos everywhere.",
    "you_guys_are_getting_paid": "DISCOVERING EVERYONE ELSE GOT SOMETHING: Tobey Maguire's surprised face — 'you guys are getting paid?' — realizing everyone else had access to a benefit, bonus, or perk you didn't know about. E.g. finding out the whole team got extra time off you weren't told about.",
    "a_train_hitting_a_school_bus": "UNSTOPPABLE VISIBLE DISASTER: A train about to hit a bus stuck on the tracks — a disaster you can clearly see coming and are powerless to stop. E.g. watching a project deadline collide with an obviously insufficient timeline, brace-for-impact energy.",
    "i_m_the_captain_now":     "HOSTILE TAKEOVER: 'Look at me. I am the captain now' — seizing control of a role or situation, someone new asserting ownership of what you were running. E.g. a new hire confidently taking over a project on day one.",
    "i_bet_he_s_thinking_about_other_women": "REVEALING THE REAL THOUGHT BUBBLE: A person smiling with a visible thought bubble exposing what they're ACTUALLY thinking about, contradicting what they claim. E.g. someone saying they're 'fully focused' while visibly thinking about lunch.",
    "blank_nut_button":        "COMPULSIVE BUTTON-MASHING: Frantically, repeatedly pressing a big red button — compulsively doing something you know you shouldn't, unable to stop. E.g. compulsively refreshing a pull request.",
    "george_bush_9_11":        "THE MOMENT EVERYTHING CHANGED: 'And then the towers fell' — a specific, date-stamped moment after which everything was different, before/after framing. E.g. 'and then the outage happened' as the dividing line for a whole quarter's plans.",
    "0_days_without_lenny_simpsons": "SAFETY COUNTER RESET AGAIN: A safety counter reset back to 0 — something went wrong again, and the streak of avoiding it just ended. E.g. '0 days without a merge conflict,' resetting yet again.",
    "trump_bill_signing":      "THEATRICAL OFFICIAL DECREE: Dramatically signing a document at a desk — an exaggeratedly formal, theatrical declaration that something is now official. E.g. dramatically 'signing off' on a decision that didn't need nearly this much ceremony.",
    "anime_girl_hiding_from_terminator": "HIDING FROM SOMETHING ACTIVELY HUNTING YOU: Hiding behind a pole or object from an approaching threat — genuine dread of something dangerous closing in. E.g. hiding from a manager who's looking for whoever broke the build.",
    "bugs_bunny_communist":    "IRONIC CHAOTIC SOLUTION: Bugs Bunny in a Soviet hat — 'allow me to introduce some communism' — proposing an ironic, chaotic-neutral, collectivist fix to a problem. E.g. jokingly proposing everyone just shares one login instead of fixing permissions properly.",
    "say_the_line_bart_simpsons": "CROWD DEMANDS THE CATCHPHRASE: 'Say the line, Bart!' — a crowd or group demanding someone perform their predictable, expected line or move on cue. E.g. the team demanding the same joke or comment someone always makes in stand-up.",
    "megamind_no_bitches":     "SHOCKED AT ZERO: 'No bitches?' — genuine disbelief that someone has none of a thing everyone else obviously has; the shock IS the joke. E.g. someone admitting they've never seen a hit movie everyone's watched. NOT watching from outside as an excluded observer (megamind_peeking).",
    "megamind_peeking":        "EXCLUDED PEEKING OBSERVER: Peering in through a tiny window or gap at something happening without you — outside looking in, not part of it. E.g. watching your friend group's plans unfold in a group chat you got removed from. NOT shock at someone lacking a thing (megamind_no_bitches), NOT lurking with envy behind a curtain (squidward_window).",
    "roll_safe_think_about_it": "CLEVER-SOUNDING TERRIBLE LOGIC: Tapping your temple — 'can't X if you never Y'; sounds like a galaxy-brain hack but is actually bad logic used to dodge a real problem. E.g. 'can't fail the test if you never take it,' or 'can't get roasted in code review if you never push code.' NOT a technically-true-but-wrong answer someone else gives you (well_yes_but_actually_no).",
    "theyre_the_same_picture": "FALSELY CLAIMED IDENTICAL: Holding up two photos that are actually the same, insisting anyone who distinguishes them is wrong. E.g. two job postings with wildly different titles but identical responsibilities.",
    "third_world_skeptical_kid": "SUSPICIOUS OF SOMETHING TOO CONVENIENT: A skeptical raised eyebrow at a claim that sounds implausibly convenient or too good to be true. E.g. side-eyeing a 'quick 5-minute fix' estimate.",
    "this_is_where_i_d_put_my_trophy_if_i_had_one": "EMPTY SPACE FOR SOMETHING NEVER EARNED: An empty shelf or display case — 'this is where I'd put X, if I had one' — wanting something you've never managed to get. E.g. an empty spot on the resume for an award you never won.",
    "aj_styles_undertaker":    "LEGENDARY UNEXPECTED CONFRONTATION: Two legendary rivals meeting unexpectedly — a confrontation between two giants from completely different worlds. E.g. two completely unrelated problems colliding at the worst possible time.",
    "grant_gustin_over_grave": "UNBOTHERED ABOUT IMPENDING DOOM: Cheerfully posing over your own grave — surprisingly at peace with a terrible, doom-laden outcome. E.g. calmly accepting a project is doomed while still smiling for the retro slide.",
    "drake_blank":             "BLANK TWO-PANEL COMPARISON: The Drake pose without preset labels — a blank canvas version of drake's reject-then-approve format for a fully custom two-option comparison. Same emotional shape as drake; use when the specific pairing doesn't fit drake's existing preset framing.",
    "mother_ignoring_kid_drowning_in_a_pool": "DANGEROUSLY DISTRACTED BY SOMETHING ELSE: Completely absorbed in one thing (a phone call) while something urgent unfolds right next to you, unnoticed. E.g. scrolling social media while a production alert quietly piles up, oblivious to the urgency.",
    "scientist_myself":        "UNEARNED INSIDER CLAIM: 'I'm something of a scientist myself' — claiming insider expertise or relatable status in something you're really not qualified in. E.g. confidently weighing in on a technical decision outside your actual expertise.",
    "empire_state_climbers":   "CASUAL CHAT MID-CRISIS: Two people having a totally unrelated, relaxed side conversation while climbing toward a high-stakes crisis. E.g. calmly discussing lunch plans in the middle of an active production incident.",
    "shut_up_and_take_my_money": "INSTANT MUST-HAVE ENERGY: Fry from Futurama throwing money at the screen — wanting something so badly you'd pay anything for it immediately. E.g. seeing a tool that finally fixes your exact workflow problem and wanting it instantly.",

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
    "baburao":          "CONFIDENTLY WRONG JUGAAD FIX: Baburao Apte (Paresh Rawal) from Hera Pheri — delivering an absurd, overconfident 'solution' as if it's genius, when it's clearly a terrible fix. E.g. proposing to 'just restart it' as the confident fix to a complex bug. NOT calm scheming (circuit_plan) — this is loud overconfidence in a bad idea.",
    "raju_hera_pheri":  "DESI SWAGGER, UNBOTHERED CONFIDENCE: Raju (Akshay Kumar) in his colourful shirt — cool, stylish, unbothered energy walking into any situation. E.g. strolling into a chaotic meeting completely unfazed, 'main hoon na' confidence.",
    "srk_ddlj":         "JUST-IN-TIME DRAMATIC REUNION: Shah Rukh Khan and Kajol's iconic train-platform reach — barely making it in time, a last-minute dramatically-timed catch or reunion. E.g. submitting a form seconds before the deadline.",
    "dhoni_calm":       "ICE-COLD UNDER PRESSURE: MS Dhoni's legendary calm — completely unbothered composure while everyone else panics under extreme pressure. E.g. calmly debugging a live outage while the whole team is panicking around you.",
    "circuit_plan":     "CALM SCHEMING JUGAAD: Circuit (Arshad Warsi) on the phone, confidently executing a dubious plan — calm, scheming problem-solving with zero real qualifications. E.g. quietly plotting an unconventional workaround instead of the 'proper' fix. NOT loud overconfident wrongness (baburao) — this is calm scheming, not blustering.",
    "jethalal_panic":   "ESCALATING 4-PANEL DREAD: Jethalal — mounting panic across four panels as the consequences of getting caught sink in. E.g. slowly realizing your mistake is about to be discovered by your manager, panel by panel.",
    "alliswel":         "FORCED POSITIVITY AMID COLLAPSE: 'All is well' — chanting fake reassurance to yourself and others as things visibly fall apart. E.g. insisting the project is 'totally on track' while the deadline quietly implodes.",
    "mogambo_khush":    "VILLAIN SATISFACTION WHEN THE PLAN WORKS: Mogambo's sinister grin — evil satisfaction when your plan succeeds, when karma hits, or when you were right all along. E.g. smiling when the thing you warned everyone about finally happens.",
    "sholay_gabbar":    "MENACING ACCOUNTABILITY DEMAND: Gabbar Singh — 'Kitne aadmi the' — demanding accountability for a failure with real menace. E.g. sternly asking who forgot to run the tests before the broken deploy.",
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

{few_shot_block}{avoid_block}{humor_block}Templates:
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


_OVERALL_TIMEOUT_SECONDS = 45.0


async def parse_intent(
    user_message: str,
    avoid_templates: list[str] | None = None,
    loved_templates: list[str] | None = None,
    hated_templates: list[str] | None = None,
) -> IntentResponse:
    """
    Route a user message to the best meme template + captions.

    avoid_templates: list of recently used template IDs in this conversation —
    injected into the prompt to prevent repetition.

    loved_templates / hated_templates: Growth Phase C humor profile — an
    anon user's aggregate feedback history (db.fetch_humor_profile), a light
    nudge rather than a hard rule. None/empty when there's no anon id, no
    DATABASE_URL, or not enough feedback yet to be confident.

    Bounded to _OVERALL_TIMEOUT_SECONDS total — the two attempts inside
    _parse_intent_inner() each carry their own per-call timeout, but a
    pathological run (429s on both the primary AND retry attempts, each
    internally retrying once inside call_groq()) can compound past 90s with
    zero events reaching the caller. A hang with no fallback is strictly
    worse than the existing hard fallback below arriving a little late, so
    this outer boundary guarantees SOME response within a fixed ceiling.
    """
    try:
        return await asyncio.wait_for(
            _parse_intent_inner(user_message, avoid_templates, loved_templates, hated_templates),
            timeout=_OVERALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return IntentResponse(
            template_id="hide_the_pain_harold",
            texts={
                "top_text": user_message[:60] if len(user_message) <= 60 else user_message[:57] + "...",
                "bottom_text": "This is fine.",
            },
            reasoning="Fallback: timed out before producing a result",
        )


_RAG_N_RESULTS = 8
_EXAMPLES_N_RESULTS = 3
_PROMPT_ID_CAP = 25


async def resolve_prompt_template_ids(user_message: str, known_id_set: set[str]) -> list[str]:
    """The RAG candidate-set resolution step: core templates (always
    guaranteed in the prompt) plus the most semantically relevant RAG
    matches, capped at _PROMPT_ID_CAP total.

    Extracted out of _parse_intent_inner so scripts/eval_template_matching.py
    can call the exact same live logic instead of hand-copying it the way
    scripts/eval_intent_models.py does — otherwise an eval script tests a
    frozen snapshot that silently drifts from reality the moment these
    parameters change (which is the entire point of the RAG-tuning phase
    this function was extracted for).

    query_similar_memes is sync (ChromaDB's EmbeddingFunction protocol
    requires it) and, with Gemini configured, makes a real network call —
    run in a thread so a slow/stalled Gemini round-trip doesn't block the
    event loop for other concurrent requests being served by this process.
    """
    rag_results = await asyncio.to_thread(query_similar_memes, user_message, n_results=_RAG_N_RESULTS)
    rag_ids = [r["id"] for r in rag_results if r.get("id") in known_id_set]

    # Core templates always come first (guaranteed in prompt); unique RAG extras appended after.
    # Cap at 25 — 70b handles ~25 compact JSON entries well within its context window.
    core_set = set(_CORE_TEMPLATE_IDS)
    extra_rag = [id for id in rag_ids if id not in core_set]
    return (_CORE_TEMPLATE_IDS + extra_rag)[:_PROMPT_ID_CAP]


async def _parse_intent_inner(
    user_message: str,
    avoid_templates: list[str] | None = None,
    loved_templates: list[str] | None = None,
    hated_templates: list[str] | None = None,
) -> IntentResponse:
    settings = get_settings()

    # All known IDs (used for validation only — NOT sent wholesale to the LLM)
    all_ids = list_template_ids() or _FALLBACK_TEMPLATES
    known_id_set = set(all_ids)

    prompt_ids = await resolve_prompt_template_ids(user_message, known_id_set)
    template_ids = prompt_ids  # used in retry prompt below
    catalog = _build_template_catalog(prompt_ids)

    examples = await asyncio.to_thread(get_similar_examples, user_message, n_results=_EXAMPLES_N_RESULTS)
    few_shot_block = _format_few_shot(examples)

    avoid_block = ""
    if avoid_templates:
        avoid_block = (
            f"IMPORTANT — DO NOT repeat these recently used templates: "
            f"{', '.join(avoid_templates)}. Pick something different and fresh.\n\n"
        )

    humor_block = ""
    if loved_templates or hated_templates:
        bits = []
        if loved_templates:
            bits.append(f"tends to enjoy {', '.join(loved_templates)}-style templates")
        if hated_templates:
            bits.append(f"tends to dislike {', '.join(hated_templates)}")
        humor_block = f"This user's taste — {'; '.join(bits)}. A light nudge, never a hard rule.\n\n"

    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2),
        few_shot_block=few_shot_block,
        avoid_block=avoid_block,
        humor_block=humor_block,
    )

    async with httpx.AsyncClient() as client:
        # Attempt 1 — rich prompt with few-shot + avoid block
        try:
            raw = await call_llm(client, settings, [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ])
            raw = strip_markdown(raw)
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
            raw = await call_llm(client, settings, [
                {"role": "user", "content": retry_prompt},
            ], temperature=0.2)
            raw = strip_markdown(raw)
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
