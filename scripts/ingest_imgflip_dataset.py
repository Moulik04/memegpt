"""
Ingest the Imgflip 100k meme dataset into the few-shot examples store.

Dataset source (free, no login required via direct download):
  https://www.kaggle.com/datasets/dylanrayn/imgflip-meme-generator-100k
  Or search Kaggle for: "imgflip meme generator dataset"

The CSV has columns: template_name, top_text, bottom_text
Each row is a real generated meme — we store it as a user_message→template
mapping so the LLM can learn from 100k real examples via RAG retrieval.

Usage:
  cd backend && source .venv/bin/activate
  python3 ../scripts/ingest_imgflip_dataset.py /path/to/imgflip_data.csv

  # To limit rows (fast test run):
  python3 ../scripts/ingest_imgflip_dataset.py /path/to/imgflip_data.csv --limit 5000
"""

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from vector_db.examples_store import example_count, upsert_example

# Map Imgflip display names → our internal template_id slugs
TEMPLATE_NAME_MAP: dict[str, str] = {
    "Drake Hotline Bling":         "drake",
    "Distracted Boyfriend":        "distracted_boyfriend",
    "Gru's Plan":                  "grus_plan",
    "Woman Yelling At Cat":        "woman_yelling_at_cat",
    "Expanding Brain":             "expanding_brain",
    "Two Buttons":                 "two_buttons",
    "Batman Slapping Robin":       "batman_slapping_robin",
    "Buff Doge vs. Cheems":        "buff_doge_vs_cheems",
    "Surprised Pikachu":           "surprised_pikachu",
    "This Is Fine":                "this_is_fine",
    "Change My Mind":              "change_my_mind",
    "Success Kid":                 "success_kid",
    "One Does Not Simply":         "one_does_not_simply",
    "Doge":                        "doge",
    "Mocking Spongebob":           "mocking_spongebob",
    "Hide the Pain Harold":        "hide_the_pain_harold",
    "Always Has Been":             "always_has_been",
    "Left Exit 12 Off Ramp":       "left_exit_12",
    "Galaxy Brain":                "galaxy_brain",
    "Anakin Padme":                "anakin_padme",
    "The Most Interesting Man In The World": "most_interesting_man",
    "Y U No":                      "y_u_no",
    "Ancient Aliens":              "ancient_aliens",
    "Boardroom Meeting Suggestion": "boardroom_suggestion",
    "First World Problems":        "first_world_problems",
    "Bad Luck Brian":              "bad_luck_brian",
    "Scumbag Steve":               "scumbag_steve",
    "Good Guy Greg":               "good_guy_greg",
    "Futurama Fry":                "futurama_fry",
    "Grumpy Cat":                  "grumpy_cat",
    "Philosoraptor":               "philosoraptor",
}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Imgflip 100k dataset into examples store")
    parser.add_argument("csv_path", help="Path to the Imgflip CSV file")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to ingest (0 = all)")
    args = parser.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        print(f"File not found: {args.csv_path}")
        sys.exit(1)

    count = 0
    skipped = 0

    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.limit and count >= args.limit:
                break

            # Normalize column names — dataset variants differ in casing/naming
            row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items()}

            template_name = (
                row.get("template_name") or row.get("meme_name") or row.get("name") or ""
            ).strip()
            top_text = (row.get("top_text") or row.get("top") or "").strip()
            bottom_text = (row.get("bottom_text") or row.get("bottom") or "").strip()

            # Skip rows with no text content
            if not template_name or (not top_text and not bottom_text):
                skipped += 1
                continue

            # Skip extremely short or noisy entries
            combined = f"{top_text} {bottom_text}".strip()
            if len(combined) < 5:
                skipped += 1
                continue

            template_id = TEMPLATE_NAME_MAP.get(template_name) or slugify(template_name)

            # The joined captions serve as the synthetic "user message" for retrieval
            user_message = " / ".join(filter(None, [top_text, bottom_text]))

            upsert_example(
                user_message=user_message,
                template_id=template_id,
                texts={"top_text": top_text, "bottom_text": bottom_text} if bottom_text
                      else {"top_text": top_text},
            )
            count += 1
            if count % 2000 == 0:
                print(f"  Ingested {count:,} examples...")

    print(f"\nDone. Ingested {count:,} rows, skipped {skipped:,} empty rows.")
    print(f"Total examples in store: {example_count():,}")


if __name__ == "__main__":
    main()
