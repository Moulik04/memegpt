"""
Prepare the Imgflip 100k dataset for instruction fine-tuning.

Input:  Imgflip CSV with columns: template_name, top_text, bottom_text
Output: memegpt_train.jsonl in the ChatML / Llama-3 instruction format

Usage:
  python3 scripts/prepare_finetune_dataset.py \\
      --csv ~/Downloads/imgflip_data.csv \\
      --out scripts/memegpt_train.jsonl \\
      --limit 20000   # optional row cap (start small on free Colab)

The output JSONL has one JSON object per line:
  {
    "messages": [
      {"role": "system",    "content": "...MemeGPT system prompt..."},
      {"role": "user",      "content": "the meme caption text"},
      {"role": "assistant", "content": "{\"template_id\": ..., \"texts\": {...}}"}
    ]
  }
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "You are MemeGPT. Given a user message, respond ONLY with a valid JSON object "
    "containing the best meme template and captions:\n"
    '{"template_id": "<id>", "texts": {"<box>": "<caption>"}, "reasoning": "<why>"}\n'
    "Be culturally sharp and genuinely funny. Never add explanation outside the JSON."
)

TEMPLATE_NAME_MAP: dict[str, str] = {
    "Drake Hotline Bling":              "drake",
    "Distracted Boyfriend":             "distracted_boyfriend",
    "Gru's Plan":                       "grus_plan",
    "Woman Yelling At Cat":             "woman_yelling_at_cat",
    "Expanding Brain":                  "expanding_brain",
    "Two Buttons":                      "two_buttons",
    "Batman Slapping Robin":            "batman_slapping_robin",
    "Buff Doge vs. Cheems":             "buff_doge_vs_cheems",
    "Surprised Pikachu":                "surprised_pikachu",
    "This Is Fine":                     "this_is_fine",
    "Change My Mind":                   "change_my_mind",
    "Success Kid":                      "success_kid",
    "One Does Not Simply":              "one_does_not_simply",
    "Doge":                             "doge",
    "Mocking Spongebob":                "mocking_spongebob",
    "Hide the Pain Harold":             "hide_the_pain_harold",
    "Always Has Been":                  "always_has_been",
    "Left Exit 12 Off Ramp":            "left_exit_12",
    "Galaxy Brain":                     "galaxy_brain",
    "Anakin Padme 4 Panel":             "anakin_padme",
    "Futurama Fry":                     "futurama_fry",
    "Bad Luck Brian":                   "bad_luck_brian",
    "Good Guy Greg":                    "good_guy_greg",
    "Scumbag Steve":                    "scumbag_steve",
    "Grumpy Cat":                       "grumpy_cat",
    "Philosoraptor":                    "philosoraptor",
    "Disaster Girl":                    "disaster_girl",
    "Crying Cat":                       "crying_cat",
    "Roll Safe Think About It":         "rollsafe",
    "Arthur Fist":                      "arthur_fist",
    "Monkey Puppet":                    "monkey_puppet",
    "Trade Offer":                      "trade_offer",
    "They're The Same Picture":         "theyre_the_same_picture",
    "Is This A Pigeon":                 "is_this_a_pigeon",
    "Panik Kalm Panik":                 "panik_kalm_panik",
    "Waiting Skeleton":                 "waiting_skeleton",
    "Among Us":                         "among_us",
    "Stonks":                           "stonks",
}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to Imgflip CSV file")
    parser.add_argument("--out", default="scripts/memegpt_train.jsonl", help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=0, help="Max examples (0 = all)")
    parser.add_argument("--min-len", type=int, default=8, help="Min combined caption length")
    args = parser.parse_args()

    in_path = Path(args.csv)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        print(f"CSV not found: {in_path}")
        sys.exit(1)

    count = 0
    skipped = 0

    with open(in_path, newline="", encoding="utf-8", errors="replace") as f_in, \
         open(out_path, "w", encoding="utf-8") as f_out:

        reader = csv.DictReader(f_in)
        for row in reader:
            if args.limit and count >= args.limit:
                break

            row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items()}
            template_name = (row.get("template_name") or row.get("meme_name") or "").strip()
            top = (row.get("top_text") or row.get("top") or "").strip()
            bottom = (row.get("bottom_text") or row.get("bottom") or "").strip()

            if not template_name or len(f"{top} {bottom}".strip()) < args.min_len:
                skipped += 1
                continue

            template_id = TEMPLATE_NAME_MAP.get(template_name) or slugify(template_name)

            # Synthetic user message = joined captions (what a human might have said)
            user_message = " / ".join(filter(None, [top, bottom]))

            texts: dict[str, str] = {}
            if top:
                texts["top_text"] = top
            if bottom:
                texts["bottom_text"] = bottom

            assistant_reply = json.dumps({
                "template_id": template_id,
                "texts": texts,
                "reasoning": f"Caption matches the {template_name} format.",
            })

            record = {
                "messages": [
                    {"role": "system",    "content": SYSTEM_PROMPT},
                    {"role": "user",      "content": user_message},
                    {"role": "assistant", "content": assistant_reply},
                ]
            }
            f_out.write(json.dumps(record) + "\n")
            count += 1

            if count % 5000 == 0:
                print(f"  Processed {count:,} examples...")

    print(f"\nWrote {count:,} training examples to {out_path}")
    print(f"Skipped {skipped:,} empty/short rows.")
    print(f"\nNext step — run on Colab/Bridges2:")
    print(f"  python3 scripts/finetune_unsloth.py --data {out_path}")


if __name__ == "__main__":
    main()
