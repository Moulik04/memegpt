"""
Precomputes Gemini embeddings for every template in backend/templates/ and
writes them to backend/data/template_embeddings.json — checked into git
(see the .gitignore exception).

**Why this exists**: template descriptions are static — they only change
when someone edits USE_WHEN or adds a new template, a rare deliberate
event. Before this script, that static text was being re-embedded live
against Gemini's API on EVERY backend restart (Render's free-tier disk is
ephemeral, so ChromaDB's collection never survives a restart). Gemini's
free tier caps at 100 requests/minute AND 1000/day, and a single
122-template reseed in chunks of 20 burns most of the per-minute budget by
itself — a handful of restarts in quick succession is enough to exhaust
even the daily cap, since there's no short retry that gets past that one
(see gemini_embedding_function.py's module docstring).

With this file checked in, main.py's _auto_seed_if_empty() loads
precomputed vectors directly instead of calling Gemini live for any
template already covered here — zero Gemini calls needed for template
seeding on a normal restart, regardless of how often Render restarts.

**Re-run this whenever templates or their USE_WHEN descriptions change** —
stale entries just mean main.py falls back to a live (Gemini) embed for
those specific templates only (graceful degrade, not a hard failure), but
keeping this file current is what keeps startup Gemini-call-free.

Run:
    cd backend && source .venv/bin/activate
    python -m scripts.precompute_template_embeddings

Needs a real GEMINI_API_KEY (uses the same generous 6-retry/61s-per-chunk
budget GeminiEmbeddingFunction already has for background/offline work —
this script is never on the production hot path, so patient pacing here
costs nothing). Safe to interrupt and re-run: already-computed entries in
the existing output file are kept unless a template's description
actually changed, so re-running after a small USE_WHEN edit doesn't
re-embed the other 120+ unchanged templates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings  # noqa: E402
from nlp.intent_router import USE_WHEN  # noqa: E402
from vector_db.chroma_client import template_document_text  # noqa: E402
from vector_db.gemini_embedding_function import GeminiEmbeddingFunction  # noqa: E402

TEMPLATES_DIR = BACKEND_DIR / "templates"
OUTPUT_PATH = BACKEND_DIR / "data" / "template_embeddings.json"
_TEMPLATE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CHUNK_SIZE = 20  # matches main.py's _SEED_CHUNK_SIZE — no reason to differ


def _collect_records() -> list[dict]:
    records = []
    for img in sorted(TEMPLATES_DIR.iterdir()):
        if img.suffix.lower() not in _TEMPLATE_IMAGE_EXTENSIONS:
            continue
        tid = img.stem
        name = tid.replace("_", " ").title()
        description = USE_WHEN.get(tid, f"Meme template: {name}")
        tags = [tid]
        records.append({
            "template_id": tid,
            "name": name,
            "tags": tags,
            "description": description,
            "document": template_document_text(name, description, tags),
        })
    return records


def main() -> None:
    settings = get_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set — nothing to precompute (Gemini is the whole point).")
        sys.exit(1)

    records = _collect_records()
    print(f"{len(records)} templates found on disk.")

    existing: dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        existing = json.loads(OUTPUT_PATH.read_text())
        print(f"{len(existing)} entries already in {OUTPUT_PATH.name}.")

    # Only (re)embed templates that are missing or whose document text
    # actually changed — re-running after one USE_WHEN edit shouldn't
    # re-embed the other 120+ unchanged templates.
    to_embed = [
        r for r in records
        if r["template_id"] not in existing or existing[r["template_id"]].get("document") != r["document"]
    ]
    print(f"{len(to_embed)} template(s) need (re-)embedding.")

    def _save() -> None:
        # Drop entries for templates that no longer exist on disk, then
        # persist. Called after every chunk (not just at the end) so a
        # later chunk's rate-limit exhaustion can never lose earlier
        # successfully-computed chunks — without this, one late chunk
        # exhausting its retry budget would discard every earlier chunk's
        # already-computed work along with it.
        current_ids = {r["template_id"] for r in records}
        pruned = {tid: entry for tid, entry in existing.items() if tid in current_ids}
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Compact, not indent=2 — this file is 121 entries x 3072 floats,
        # nobody hand-edits or reviews it, and pretty-printing roughly
        # doubles the size for pure whitespace with no real benefit.
        OUTPUT_PATH.write_text(json.dumps(pruned, separators=(",", ":")))

    if to_embed:
        embedder = GeminiEmbeddingFunction(
            model_name=settings.gemini_embedding_model,
            api_key=settings.gemini_api_key,
        )
        failed = 0
        for i in range(0, len(to_embed), _CHUNK_SIZE):
            chunk = to_embed[i : i + _CHUNK_SIZE]
            print(f"  Embedding chunk {i // _CHUNK_SIZE + 1} ({len(chunk)} templates)...")
            try:
                raw_vectors = embedder([r["document"] for r in chunk])
            except Exception as exc:
                # One chunk failing (e.g. Gemini's daily quota genuinely
                # exhausted, not just a transient 429 the retry budget
                # already rode out) must not lose every other chunk's
                # already-computed work — re-run the script later to pick
                # up exactly what's still missing.
                print(f"  [error] Chunk failed, skipping (re-run later to retry): {exc}")
                failed += len(chunk)
                continue
            # GeminiEmbeddingFunction's declared return type is a plain
            # list of lists, but ChromaDB's EmbeddingFunction base class
            # coerces it through numpy — both the outer array AND each
            # individual element (numpy.float32, not a plain float) need
            # unwrapping before json.dumps() can serialize this.
            vectors = [[float(x) for x in v] for v in raw_vectors]
            for record, vector in zip(chunk, vectors):
                existing[record["template_id"]] = {
                    "embedding": vector,
                    "document": record["document"],
                    "name": record["name"],
                    "tags": record["tags"],
                    "description": record["description"],
                }
            _save()  # incremental — see _save()'s own docstring comment above

        if failed:
            print(f"\n{failed} template(s) failed to embed this run — re-run the script to retry just those.")

    _save()
    print(f"\nWrote {len(existing)} precomputed embeddings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
