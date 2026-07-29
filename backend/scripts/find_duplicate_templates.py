"""
Two complementary sweeps over backend/templates/ to find duplicate or
near-duplicate template images — the same source picture saved under two
different template_ids, which is a real source of LLM template-matching
confusion (both ids describe the same visual, so the model has no reliable
way to pick between them).

1. Perceptual hash (dHash, pure Pillow, no new dependency): catches true
   pixel-level duplicates — same source image, different crop/compression/
   watermark — reliably at similarity >= ~0.95. Confirmed by finding two
   exact 1.000 matches this way, both verified visually as true duplicates.

2. Description-text embedding similarity (reuses GeminiEmbeddingFunction,
   the same one wired into ChromaDB): catches the case dHash misses —
   the SAME meme concept, photographed/cropped differently enough that the
   pixel gradient no longer lines up. This is exactly how the
   look_at_me/i_m_the_captain_now duplicate was first found (by noticing
   both USE_WHEN entries described "I am the captain now") — its dHash
   similarity is only 0.605, nowhere near dHash's own duplicate threshold,
   proving image hashing alone isn't sufficient here.

Neither pass auto-deletes anything — below each method's high-confidence
band, matches increasingly reflect coincidental similarity (comparable
composition/lighting, or just similar wording) rather than a true
duplicate, and need a human look.

Run: cd backend && python -m scripts.find_duplicate_templates
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

from PIL import Image

from config import get_settings
from nlp.intent_router import USE_WHEN
from vector_db.gemini_embedding_function import get_embedding_function

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_HASH_SIZE = 16  # 16x16 -> 256-bit hash
_TOP_N = 30


def dhash(path: Path, hash_size: int = _HASH_SIZE) -> int:
    img = Image.open(path).convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(img.getdata())
    bits = 0
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _template_ids() -> list[str]:
    return sorted(
        f.stem
        for f in _TEMPLATES_DIR.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def run_image_hash_sweep() -> None:
    files = [
        f
        for f in sorted(_TEMPLATES_DIR.iterdir())
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    hashes: dict[str, int] = {}
    for f in files:
        try:
            hashes[f.name] = dhash(f)
        except Exception as e:
            print(f"FAILED to hash {f.name}: {e}")

    total_bits = _HASH_SIZE * _HASH_SIZE
    results = []
    for a, b in itertools.combinations(hashes.keys(), 2):
        dist = hamming(hashes[a], hashes[b])
        similarity = 1 - dist / total_bits
        results.append((similarity, a, b))

    results.sort(reverse=True)
    print(f"=== Image hash (dHash) — hashed {len(hashes)} templates ===")
    print(f"Top {_TOP_N} most similar pairs:\n")
    for sim, a, b in results[:_TOP_N]:
        flag = " <- likely true duplicate, review" if sim >= 0.95 else ""
        print(f"{sim:.3f}  {a}  <->  {b}{flag}")


def run_description_embedding_sweep() -> None:
    settings = get_settings()
    embedding_function = get_embedding_function(settings)
    if embedding_function is None:
        print(
            "\n(Skipping description-embedding sweep — GEMINI_API_KEY not set. "
            "The image-hash sweep above still runs without it.)"
        )
        return

    ids = _template_ids()
    documents = [
        f"{tid.replace('_', ' ')}. {USE_WHEN.get(tid, '')}".strip() for tid in ids
    ]
    vectors = embedding_function(documents)

    results = []
    for (id_a, vec_a), (id_b, vec_b) in itertools.combinations(zip(ids, vectors), 2):
        results.append((cosine_similarity(vec_a, vec_b), id_a, id_b))

    results.sort(reverse=True)
    print(f"\n=== Description-embedding similarity — {len(ids)} templates ===")
    print(f"Top {_TOP_N} most similar pairs:\n")
    for sim, a, b in results[:_TOP_N]:
        print(f"{sim:.3f}  {a}  <->  {b}")


def main() -> None:
    run_image_hash_sweep()
    run_description_embedding_sweep()


if __name__ == "__main__":
    main()
