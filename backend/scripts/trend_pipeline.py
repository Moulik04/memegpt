"""
Weekly, fully automated template discovery.

Fetches Imgflip's free public template list, diffs it against the ~118
templates already in backend/templates/, and for genuinely new candidates
(name doesn't match an existing file AND the image isn't a perceptual-hash
near-duplicate of one we already have under a different name): downloads
the image, runs it through the same content-moderation gate every
user-uploaded image goes through, asks a vision LLM to draft a
USE_WHEN-style catalog entry, precomputes its Gemini embedding, and
commits the new template file plus its USE_WHEN entry plus its embedding
directly to main. No PR, no human review step — the automated gates
(perceptual-hash dedup, content moderation, and the workflow's own
pytest run before it ever commits) are what stand in for one. A template
that clears every gate is live on the next deploy, available to Chat,
Lore, and Make alike, the same as a hand-curated one.

Run:
    cd backend && python -m scripts.trend_pipeline --dry-run   # no Groq/Gemini calls, no writes
    cd backend && python -m scripts.trend_pipeline              # real run, needs GROQ_API_KEY + GEMINI_API_KEY

Reuses (not reimplements) four existing precedents:
- scripts/seed_templates.py's Imgflip fetch shape (public API, no auth).
- scripts/find_duplicate_templates.py's dhash()/hamming() perceptual-hash
  primitives, already validated on this exact catalog (see that file's
  docstring).
- uploads/moderation.py's moderate_image() — the exact same fail-closed
  content-safety gate every user-uploaded photo already goes through.
- scripts/precompute_template_embeddings.py's embedding shape
  (GeminiEmbeddingFunction + template_document_text()), so a
  trend-pipeline-added template's embedding is indistinguishable from one
  added by that script by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx
from PIL import Image

from config import get_settings
from nlp.intent_router import _CORE_TEMPLATE_IDS, USE_WHEN
from nlp.llm_client import strip_markdown
from nlp.vision import call_groq_vision
from scripts.find_duplicate_templates import dhash, hamming
from uploads.moderation import moderate_image
from vector_db.chroma_client import template_document_text
from vector_db.gemini_embedding_function import GeminiEmbeddingFunction

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
INTENT_ROUTER_PATH = Path(__file__).resolve().parent.parent / "nlp" / "intent_router.py"
EMBEDDINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "template_embeddings.json"
COMMIT_BODY_PATH = Path(__file__).resolve().parent.parent / "trend_pipeline_commit_body.md"

IMGFLIP_API = "https://api.imgflip.com/get_memes"
_HASH_SIZE = 16  # must match find_duplicate_templates.py's default
_DUPLICATE_THRESHOLD = 0.95  # same confirmed threshold as find_duplicate_templates.py

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# The catalog's known confusion clusters (from the USE_WHEN cross-reference
# notes in nlp/intent_router.py) — surfaced directly in every PR body so
# the human reviewer doesn't have to go hunting for it.
_KNOWN_CONFUSION_CLUSTERS = [
    "drake / evil_kermit / two_buttons",
    "distracted_boyfriend / left_exit_12 / uno_draw_25_cards",
    "leonardo_dicaprio_cheers / laughing_leo",
    "spiderman_pointing_at_spiderman / spider_man_triple",
    "megamind_no_bitches / megamind_peeking",
    "is_this_a_pigeon / theyre_the_same_picture",
    "bell_curve / midwit_bell_curve",
]

_DRAFT_SYSTEM_PROMPT = """\
You write catalog entries for a meme-template picker, in the exact style \
below. Look at the image and write ONE entry for it.

Style to match — CAPS label, colon, one dense sentence, then explicit \
"NOT for X (use Y)" cross-references naming specific other templates it \
could be confused with, if any of these examples below look related:

{examples}

This catalog already has these known confusion clusters — if the image in \
front of you belongs to one of them, its NOT-for cross-reference MUST name \
the specific other template(s) in its cluster, not just any vaguely \
similar one:
{clusters}

Also note whether this image is a simple single top/bottom caption format, \
or has multiple panels / a non-obvious caption layout that would need a \
custom box configuration instead of the generic top/bottom default.

Respond with ONLY valid JSON, no markdown, no explanation:
{{"use_when": "CAPS LABEL: one sentence, NOT for ... (use ...).", \
"box_layout_note": "one short sentence"}}\
"""


def slugify(name: str) -> str:
    """Identical regex to scripts/seed_templates.py's slugify() — kept as a
    separate copy rather than a cross-directory import (repo-root scripts/
    isn't on this package's import path), matching this codebase's existing
    small-duplication-over-awkward-cross-import precedent."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch_imgflip_memes() -> list[dict]:
    r = httpx.get(IMGFLIP_API, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Imgflip API returned failure: {data}")
    return data["data"]["memes"]


def diff_new_candidates(memes: list[dict], existing_slugs: set[str]) -> list[dict]:
    """Pure — no network, no filesystem. `existing_slugs` should be the
    actual template_ids on disk (TEMPLATES_DIR file stems), not any
    historical/curated name-to-id mapping, since templates can be renamed,
    removed during catalog cleanup, or added by hand.

    Deliberately a CHEAP, imprecise pre-filter, not the real dedup: our
    curated template_ids (e.g. "drake") are almost never the literal slug of
    Imgflip's own display name (e.g. "Drake Hotline Bling" -> "drake_hotline_
    bling"). So most of the real catalog will slug-mismatch and pass this
    filter every run; that's fine and expected. The actual
    "have we already got this" decision is the perceptual-hash comparison in
    _run() below, run against every survivor's downloaded image — this
    function's only job is to skip the (rare but free) exact-slug matches
    without a download."""
    return [meme for meme in memes if slugify(meme["name"]) not in existing_slugs]


def _existing_template_ids() -> list[str]:
    return sorted(f.stem for f in TEMPLATES_DIR.iterdir() if f.suffix.lower() in _IMAGE_EXTENSIONS)


def _download(url: str) -> bytes:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _closest_existing_match(
    candidate_path: Path, existing_hashes: dict[str, int]
) -> tuple[str, float]:
    """Returns (closest existing template_id, similarity 0..1) — always
    returns something (even below the duplicate threshold) so the PR body
    can show "closest match" for transparency, not just a binary flag."""
    total_bits = _HASH_SIZE * _HASH_SIZE
    candidate_hash = dhash(candidate_path, _HASH_SIZE)
    best_id, best_sim = "", 0.0
    for tid, existing_hash in existing_hashes.items():
        sim = 1 - hamming(candidate_hash, existing_hash) / total_bits
        if sim > best_sim:
            best_id, best_sim = tid, sim
    return best_id, best_sim


def _use_when_examples_block() -> str:
    """A bounded sample (the always-in-prompt core templates), not the full
    118-entry catalog — keeps the drafting prompt small. The known
    confusion clusters (folded into _DRAFT_SYSTEM_PROMPT directly) cover
    the specific cross-catalog mixups a human reviewer used to be the
    backstop for."""
    lines = [f'- "{tid}": {USE_WHEN[tid]}' for tid in _CORE_TEMPLATE_IDS if tid in USE_WHEN]
    return "\n".join(lines)


async def _draft_use_when(image: Image.Image) -> dict | None:
    """Returns None on any failure rather than a placeholder — there's no
    human downstream to notice and fix a "DRAFT FAILED" stub before it
    reaches production, so the caller drops this candidate entirely
    instead of committing a broken catalog entry. One bad LLM call still
    can't abort the whole run; it just costs that one candidate."""
    settings = get_settings()
    system_prompt = _DRAFT_SYSTEM_PROMPT.format(
        examples=_use_when_examples_block(),
        clusters="\n".join(f"- {c}" for c in _KNOWN_CONFUSION_CLUSTERS),
    )
    try:
        raw = await call_groq_vision(
            image,
            system_prompt,
            "Draft the catalog entry for this template.",
            settings.vision_model,
            settings,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        data = json.loads(strip_markdown(raw))
        return {
            "use_when": str(data["use_when"]),
            "box_layout_note": str(data["box_layout_note"]),
        }
    except Exception as exc:
        print(f"  [error] catalog-entry drafting failed, dropping this candidate: {exc}")
        return None


def insert_use_when_entries(source: str, new_entries: dict[str, str]) -> str:
    """Pure string transform — anchors on the literal `USE_WHEN: dict[str,
    str] = {` line and the first column-0 `}` after it. Raises ValueError
    (never silently corrupts the file) if either anchor isn't found exactly
    once, which would mean intent_router.py's format has drifted since this
    was written."""
    open_marker = "USE_WHEN: dict[str, str] = {"
    open_idx = source.find(open_marker)
    if open_idx == -1 or source.find(open_marker, open_idx + 1) != -1:
        raise ValueError("USE_WHEN opening marker not found exactly once — refusing to edit")

    search_from = open_idx + len(open_marker)
    close_idx = source.find("\n}", search_from)
    if close_idx == -1:
        raise ValueError("USE_WHEN closing brace not found — refusing to edit")

    # ensure_ascii=False — the rest of this dict is full of literal em
    # dashes ("SETTLED PREFERENCE: A verdict already reached — smugly...");
    # json.dumps' default would escape them to —, which is valid but
    # visually inconsistent with every neighboring entry.
    new_lines = "".join(
        f'    "{tid}": {json.dumps(text, ensure_ascii=False)},\n' for tid, text in new_entries.items()
    )
    # Section header makes it obvious in the diff which entries came from
    # this automated pass, distinct from hand-curated ones above it.
    header = "    # --- Trend pipeline additions (auto-merged) ---\n"
    new_source = source[:close_idx] + "\n" + header + new_lines + source[close_idx:]

    # Refuse to write a source file that doesn't even parse — the string
    # surgery above is anchor-based, not AST-based, so this is the one
    # cheap check standing between a quoting edge case and a broken
    # intent_router.py landing on main with nothing else to catch it
    # before the workflow's own pytest step (which imports this module).
    try:
        compile(new_source, str(INTENT_ROUTER_PATH), "exec")
    except SyntaxError as exc:
        raise ValueError(f"Edited intent_router.py source no longer compiles — refusing to write: {exc}") from exc

    return new_source


def _merge_embeddings(existing: dict[str, dict], new_entries: dict[str, dict]) -> dict[str, dict]:
    """Pure — same incremental-merge contract as
    scripts/precompute_template_embeddings.py: new entries are added,
    every existing entry (hand-curated or from a prior trend-pipeline run)
    is kept untouched."""
    merged = dict(existing)
    merged.update(new_entries)
    return merged


def _write_commit_body(candidates: list[dict]) -> None:
    sections = []
    for c in candidates:
        sections.append(
            f"### `{c['template_id']}` — {c['display_name']}\n\n"
            f"Source: [{c['display_name']} on Imgflip]({c['imgflip_url']})\n\n"
            f"Closest existing match: `{c['closest_match_id']}` "
            f"(similarity {c['closest_match_sim']:.3f}, below the "
            f"{_DUPLICATE_THRESHOLD} duplicate threshold)\n\n"
            f"**`USE_WHEN`:**\n```python\n\"{c['template_id']}\": {json.dumps(c['use_when'])},\n```\n\n"
            f"**Box layout note:** {c['box_layout_note']} (falls back to the generic "
            f"top/bottom `DEFAULT_BOXES` layout unless someone later adds a custom "
            f"`TextBoxConfig` for it in `image_processing/template_configs.py`)\n"
        )

    body = f"""\
## New template(s) added by this week's Imgflip scan

Automated by `backend/scripts/trend_pipeline.py`. Each one cleared the \
perceptual-hash duplicate filter, the same content-moderation gate every \
user-uploaded image goes through, and the workflow's own pytest run \
before landing here — no PR, no manual merge.

{"".join(sections)}
"""
    COMMIT_BODY_PATH.write_text(body)


async def _run(dry_run: bool) -> None:
    print("Fetching Imgflip's template list...")
    memes = fetch_imgflip_memes()
    existing_ids = _existing_template_ids()
    candidates = diff_new_candidates(memes, set(existing_ids))
    print(f"{len(memes)} templates on Imgflip, {len(existing_ids)} already in the catalog, "
          f"{len(candidates)} not matched by name (expected to be most of them — our curated "
          f"template_ids rarely equal Imgflip's own display-name slug; the real dedup is the "
          f"perceptual-hash check against each one's actual image, next).")

    if not candidates:
        print("Nothing new this week.")
        return

    print("Hashing existing catalog for visual-duplicate comparison...")
    existing_hashes = {tid: dhash(_template_path(tid), _HASH_SIZE) for tid in existing_ids}

    surviving: list[dict] = []
    for meme in candidates:
        template_id = slugify(meme["name"])
        tmp_path: Path | None = None
        # One bad candidate (a broken download, a corrupt image Pillow can't
        # open) must not abort the whole weekly run and lose every OTHER
        # genuine candidate found alongside it — log and continue, matching
        # this codebase's existing "one failure in a batch doesn't sink the
        # batch" precedent (e.g. _stream_batch's per-situation try/except).
        try:
            image_bytes = _download(meme["url"])
            ext = Path(meme["url"].split("?")[0]).suffix or ".jpg"
            tmp_path = TEMPLATES_DIR / f".trend_pipeline_tmp_{template_id}{ext}"
            tmp_path.write_bytes(image_bytes)

            closest_id, closest_sim = _closest_existing_match(tmp_path, existing_hashes)
            if closest_sim >= _DUPLICATE_THRESHOLD:
                print(f"[skip] {template_id} — visual duplicate of existing `{closest_id}` "
                      f"(similarity {closest_sim:.3f}), Imgflip just calls it something else.")
                tmp_path.unlink(missing_ok=True)
                continue

            # Same fail-closed content-safety gate every user-uploaded image
            # already goes through (uploads/moderation.py) — this candidate
            # is about to become part of the public template catalog with
            # no human ever looking at it, so it gets no less scrutiny than
            # a user's own photo upload does.
            moderation = await moderate_image(Image.open(tmp_path).convert("RGB"))
            if not moderation.passed:
                print(f"[skip] {template_id} — failed content moderation "
                      f"(category: {moderation.category}).")
                tmp_path.unlink(missing_ok=True)
                continue

            print(f"[candidate] {template_id} — closest existing match `{closest_id}` "
                  f"at {closest_sim:.3f}, below the duplicate threshold, passed moderation.")
            surviving.append({
                "template_id": template_id,
                "display_name": meme["name"],
                "imgflip_url": f"https://imgflip.com/meme/{meme['id']}",
                "image_bytes": image_bytes,
                "ext": ext,
                "tmp_path": tmp_path,
                "closest_match_id": closest_id,
                "closest_match_sim": closest_sim,
            })
        except Exception as exc:
            print(f"[error] {template_id} — skipping this candidate: {exc}")
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            continue

    if dry_run:
        print(f"\n--dry-run: {len(surviving)} genuine candidate(s) found, stopping before the LLM step.")
        for c in surviving:
            c["tmp_path"].unlink(missing_ok=True)
        return

    if not surviving:
        print("No candidates survived the visual-duplicate and moderation filters.")
        return

    settings = get_settings()
    if not settings.gemini_api_key:
        # Fail loudly rather than commit templates with no embedding — an
        # un-embedded template is invisible to Chat/Lore's RAG lookup and
        # to Make's picker (both read through ChromaDB, seeded from this
        # same embeddings file), so a partial add is worse than no add.
        for c in surviving:
            c["tmp_path"].unlink(missing_ok=True)
        raise RuntimeError(
            "GEMINI_API_KEY is not set — cannot embed new templates, refusing to add "
            f"{len(surviving)} candidate(s) without one. Add it as a repo secret."
        )

    embedder = GeminiEmbeddingFunction(
        model_name=settings.gemini_embedding_model,
        api_key=settings.gemini_api_key,
    )

    added: list[dict] = []
    new_use_when: dict[str, str] = {}
    new_embeddings: dict[str, dict] = {}
    for c in surviving:
        print(f"Drafting catalog entry for {c['template_id']} (vision call)...")
        image = Image.open(c["tmp_path"]).convert("RGB")
        draft = await _draft_use_when(image)
        if draft is None:
            c["tmp_path"].unlink(missing_ok=True)
            continue
        c["use_when"] = draft["use_when"]
        c["box_layout_note"] = draft["box_layout_note"]

        name = c["template_id"].replace("_", " ").title()
        tags = [c["template_id"]]
        document = template_document_text(name, draft["use_when"], tags)
        print(f"Embedding {c['template_id']} (Gemini call)...")
        raw_vector = embedder([document])[0]
        new_embeddings[c["template_id"]] = {
            "embedding": [float(x) for x in raw_vector],
            "document": document,
            "name": name,
            "tags": tags,
            "description": draft["use_when"],
        }
        new_use_when[c["template_id"]] = draft["use_when"]

        final_path = TEMPLATES_DIR / f"{c['template_id']}{c['ext']}"
        c["tmp_path"].rename(final_path)
        added.append(c)

    if not added:
        print("No candidates survived catalog-entry drafting.")
        return

    source = INTENT_ROUTER_PATH.read_text()
    INTENT_ROUTER_PATH.write_text(insert_use_when_entries(source, new_use_when))

    existing_embeddings = json.loads(EMBEDDINGS_PATH.read_text()) if EMBEDDINGS_PATH.exists() else {}
    merged = _merge_embeddings(existing_embeddings, new_embeddings)
    EMBEDDINGS_PATH.write_text(json.dumps(merged, separators=(",", ":")))

    _write_commit_body(added)
    print(f"\nAdded {len(added)} new template(s): updated USE_WHEN, precomputed embeddings, "
          f"and wrote {COMMIT_BODY_PATH} for the commit message.")


def _template_path(template_id: str) -> Path:
    for ext in _IMAGE_EXTENSIONS:
        candidate = TEMPLATES_DIR / f"{template_id}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(template_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + diff + visual-duplicate-filter only. No Groq call, no writes, no network beyond Imgflip.",
    )
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
