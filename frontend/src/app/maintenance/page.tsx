import { Masthead } from "@/components/Masthead";

// Drawn on the server for each visit, so the page arrives with its pair
// and archive already chosen and nothing changes once it's showing.
export const dynamic = "force-dynamic";

/**
 * The 50 memes rendered by scripts/generate_maintenance_memes.py into
 * public/maintenance, with each file's own size so the grid never guesses.
 */
const ARCHIVE: Record<string, [number, number]> = {
  absolute_cinema: [936, 725],
  ah_shit_here_we_go_again: [1235, 695],
  all_my_homies_hate: [680, 615],
  anakin_padme: [768, 768],
  bike_fall: [500, 680],
  blank_nut_button: [600, 446],
  boardroom_meeting_suggestion: [500, 649],
  buff_doge_vs_cheems: [937, 720],
  but_that_s_none_of_my_business: [600, 600],
  change_my_mind: [482, 361],
  chill_guy: [1125, 1071],
  clown_applying_makeup: [750, 798],
  domino_effect: [820, 565],
  drake: [1200, 1200],
  epic_handshake: [900, 645],
  evil_kermit: [700, 325],
  expanding_brain: [857, 1202],
  flex_tape: [510, 572],
  friendship_ended: [800, 600],
  grus_plan: [700, 449],
  gus_fring_we_are_not_the_same: [700, 1000],
  hide_the_pain_harold: [480, 601],
  i_m_the_captain_now: [478, 350],
  laughing_leo: [470, 470],
  left_exit_12: [804, 767],
  leonardo_dicaprio_cheers: [600, 400],
  marked_safe_from: [618, 499],
  math_lady: [680, 445],
  mocking_spongebob: [502, 353],
  mr_incredible_uncanny: [1157, 651],
  one_does_not_simply: [568, 335],
  panik_kalm_panik: [640, 881],
  roll_safe_think_about_it: [702, 395],
  running_away_balloon: [761, 1024],
  sad_hamster: [719, 722],
  sad_pablo: [720, 709],
  scooby_doo_mask_reveal: [720, 960],
  spiderman_pointing_at_spiderman: [800, 450],
  star_wars_yoda: [620, 713],
  surprised_pikachu: [1893, 1892],
  the_rock_driving: [568, 700],
  the_scroll_of_truth: [1280, 1236],
  theyre_the_same_picture: [1363, 1524],
  this_is_fine: [580, 282],
  tuxedo_winnie_the_pooh: [800, 582],
  two_buttons: [600, 908],
  two_paths: [416, 416],
  uno_draw_25_cards: [500, 494],
  waiting_skeleton: [298, 403],
  woman_yelling_at_cat: [680, 438],
};

/** The copy deck, section 7.8: the six live pairs, unchanged. */
const PAIRS = [
  {
    h: "brb, MemeGPT is touching grass",
    s: "We're off rebuilding something even more unhinged. The servers needed a nap. Back soon.",
  },
  {
    h: "ONE DOES NOT SIMPLY ship features without downtime",
    s: "MemeGPT is getting a glow-up. Enjoy the archives while we pretend this was always the plan.",
  },
  {
    h: "MemeGPT is currently unavailable due to unprecedented demand for unhinged content",
    s: "Our engineers are working around the clock. (They are not. It's one guy. He's tired.)",
  },
  {
    h: "THIS IS FINE.",
    s: "Everything is on fire. We lit it. On purpose. For good reasons. Mostly.",
  },
  {
    h: "EXPANDING BRAIN: just 5 minutes of maintenance",
    s: "Three days later: 40 new bugs, 2 existential crises, 1 slightly better meme engine.",
  },
  {
    h: "Still loading, since forever",
    s: "Somewhere between a quick patch and a total rebuild we lost track of time. It'll be worth it. Probably.",
  },
] as const;

const ARCHIVE_COUNT = 4;

function pickArchive(): string[] {
  const ids = Object.keys(ARCHIVE);
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  return ids.slice(0, ARCHIVE_COUNT);
}

/** Served for every address while maintenance mode is on. No controls. */
export default function MaintenancePage() {
  const pair = PAIRS[Math.floor(Math.random() * PAIRS.length)];
  const archive = pickArchive();
  return (
    <div className="min-h-dvh flex flex-col bg-background">
      <Masthead variant="system" unlinked />
      <main className="flex-1 mx-auto w-full max-w-6xl px-4 md:px-8 py-8 md:py-12">
        <h1 className="font-display text-[length:var(--text-title)] leading-[0.95] text-foreground max-w-4xl">{pair.h}</h1>
        <p className="mt-4 text-lg text-foreground max-w-2xl">{pair.s}</p>
        <section aria-labelledby="archives" className="mt-10 md:mt-14">
          <h2 id="archives" className="border-t-2 border-foreground pt-2 text-sm font-bold uppercase tracking-wide text-foreground">
            From the archives
          </h2>
          <ul className="mt-4 grid grid-cols-2 md:grid-cols-4 items-start gap-3 md:gap-6">
            {archive.map((id) => (
              <li key={id} className="bg-meme-mat border border-meme-edge p-2 md:p-3">
                {/* eslint-disable-next-line @next/next/no-img-element -- natural size, still */}
                <img
                  src={`/maintenance/${id}.png`}
                  alt="A meme from the MemeGPT archives"
                  width={ARCHIVE[id][0]}
                  height={ARCHIVE[id][1]}
                  className="block w-full h-auto border border-meme-edge"
                />
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
