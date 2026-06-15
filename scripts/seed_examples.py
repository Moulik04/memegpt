"""
Seed curated few-shot meme examples into ChromaDB.

Run once (or re-run to refresh) before starting the server:
  cd backend && source .venv/bin/activate
  python3 ../scripts/seed_examples.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from vector_db.examples_store import example_count, upsert_example

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "backend" / "data" / "curated_examples.jsonl"


def main() -> None:
    if not EXAMPLES_PATH.exists():
        print(f"Examples file not found: {EXAMPLES_PATH}")
        sys.exit(1)

    lines = [l for l in EXAMPLES_PATH.read_text().strip().splitlines() if l.strip()]
    count = 0
    for line in lines:
        ex = json.loads(line)
        upsert_example(
            user_message=ex["user_message"],
            template_id=ex["template_id"],
            texts=ex["texts"],
        )
        print(f"  ✓ {ex['template_id']:30s} | {ex['user_message'][:55]}")
        count += 1

    print(f"\nSeeded {count} examples. Total in store: {example_count()}")


if __name__ == "__main__":
    main()
