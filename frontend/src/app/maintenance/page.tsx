"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Image from "next/image";
import styles from "./maintenance.module.css";

// The 50 template ids rendered by scripts/generate_maintenance_memes.py
// into public/maintenance/*.png. Kept as a plain literal here rather than
// fetched at runtime — this page is a temporary holding page, not core
// product surface, so the small manual-sync cost against that script's
// MEMES list (only changes if someone deliberately regenerates the whole
// batch) isn't worth a build-time manifest-file mechanism.
const MEME_POOL = [
  "hide_the_pain_harold", "this_is_fine", "waiting_skeleton", "expanding_brain",
  "drake", "grus_plan", "panik_kalm_panik", "surprised_pikachu", "buff_doge_vs_cheems",
  "mocking_spongebob", "one_does_not_simply", "change_my_mind", "two_buttons",
  "evil_kermit", "woman_yelling_at_cat", "boardroom_meeting_suggestion", "epic_handshake",
  "tuxedo_winnie_the_pooh", "left_exit_12", "anakin_padme", "uno_draw_25_cards",
  "leonardo_dicaprio_cheers", "laughing_leo", "all_my_homies_hate",
  "spiderman_pointing_at_spiderman", "flex_tape", "marked_safe_from", "clown_applying_makeup",
  "running_away_balloon", "absolute_cinema", "gus_fring_we_are_not_the_same", "star_wars_yoda",
  "the_rock_driving", "friendship_ended", "but_that_s_none_of_my_business",
  "scooby_doo_mask_reveal", "the_scroll_of_truth", "sad_pablo", "domino_effect", "bike_fall",
  "two_paths", "blank_nut_button", "i_m_the_captain_now", "roll_safe_think_about_it",
  "theyre_the_same_picture", "sad_hamster", "chill_guy", "ah_shit_here_we_go_again",
  "math_lady", "mr_incredible_uncanny",
] as const;

const HEADLINES = [
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

const HEADLINE_INTERVAL_MS = 10_000;
const FADE_MS = 400;

interface LaneConfig {
  top: string;
  direction: "left" | "right";
  durationS: number;
  size: number;
  delayS: number;
  opacity: number;
}

const LANE_CONFIGS: LaneConfig[] = [
  { top: "6%", direction: "right", durationS: 26, size: 128, delayS: 0, opacity: 0.9 },
  { top: "18%", direction: "left", durationS: 34, size: 96, delayS: 4, opacity: 0.55 },
  { top: "34%", direction: "right", durationS: 22, size: 150, delayS: 8, opacity: 1 },
  { top: "58%", direction: "left", durationS: 30, size: 108, delayS: 2, opacity: 0.6 },
  { top: "74%", direction: "right", durationS: 27, size: 132, delayS: 12, opacity: 0.85 },
  { top: "88%", direction: "left", durationS: 38, size: 90, delayS: 6, opacity: 0.45 },
];

const EDGE_COLORS = ["rgba(147,51,234,0.55)", "rgba(219,39,119,0.55)", "rgba(34,211,238,0.45)"];

function shuffled<T>(items: readonly T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export default function MaintenancePage() {
  const [variantIndex, setVariantIndex] = useState(0);
  const [fading, setFading] = useState(false);

  // Drawn once per mount so each lane shows a different slice of the 50
  // real memes on every page load — same "randomize per load" precedent
  // as LandingPage.tsx's floating hero thumbnails.
  const [laneMemes] = useState<string[][]>(() => {
    const pool = shuffled(MEME_POOL);
    return LANE_CONFIGS.map((_, laneIndex) =>
      [0, 1, 2].map((i) => pool[(laneIndex * 3 + i) % pool.length])
    );
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setFading(true);
      window.setTimeout(() => {
        setVariantIndex((i) => (i + 1) % HEADLINES.length);
        setFading(false);
      }, FADE_MS);
    }, HEADLINE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const variant = HEADLINES[variantIndex];

  return (
    <div className={styles.stage}>
      <div className={`${styles.blob} ${styles.blob1}`} />
      <div className={`${styles.blob} ${styles.blob2}`} />
      <div className={`${styles.blob} ${styles.blob3}`} />
      <div className={`${styles.blob} ${styles.blob4}`} />

      <div className={styles.sky}>
        {LANE_CONFIGS.map((cfg, laneIndex) => (
          <div
            key={laneIndex}
            className={`${styles.lane} ${cfg.direction === "right" ? styles.laneRight : styles.laneLeft}`}
            style={{
              top: cfg.top,
              animationDuration: `${cfg.durationS}s`,
              animationDelay: `-${cfg.delayS}s`,
              gap: "18vw",
            }}
          >
            {laneMemes[laneIndex].map((templateId, i) => {
              const height = Math.round(cfg.size * 1.1);
              const cardStyle: CSSProperties & Record<"--edge-color", string> = {
                width: cfg.size,
                height,
                opacity: cfg.opacity,
                transform: `rotate(${(laneIndex % 2 === 0 ? -1 : 1) * (3 + i)}deg)`,
                "--edge-color": EDGE_COLORS[(laneIndex + i) % EDGE_COLORS.length],
              };
              return (
                <div key={`${templateId}-${i}`} className={styles.memeCard} style={cardStyle}>
                  <Image
                    src={`/maintenance/${templateId}.png`}
                    alt=""
                    width={cfg.size}
                    height={height}
                    unoptimized
                  />
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className={styles.content}>
        <div className={styles.statusPill}>
          <span className={styles.statusDot} />
          <span>MemeGPT is off getting better</span>
        </div>
        <h1 className={fading ? `${styles.headline} ${styles.fade}` : styles.headline}>
          {variant.h}
        </h1>
        <p className={fading ? `${styles.sub} ${styles.fade}` : styles.sub}>{variant.s}</p>
        <div className={styles.variantDots}>
          {HEADLINES.map((_, i) => (
            <span key={i} className={i === variantIndex ? styles.on : undefined} />
          ))}
        </div>
      </div>
    </div>
  );
}
