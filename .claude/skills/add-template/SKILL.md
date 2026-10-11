---
name: add-template
description: Add a new meme template to the catalog end to end. Use when adding, replacing, or removing a template, or when a trend-pipeline PR needs finishing.
allowed-tools: Read Edit Bash(python*) Bash(pytest*)
---

Adding a template touches five places. Missing any one leaves the catalog
silently broken — a template that exists on disk but never gets picked, or
one that renders with the wrong layout.

1. **Image** → `backend/templates/<template_id>.<ext>`. Confirm it isn't a
   near-duplicate of an existing template first:
   `python backend/scripts/find_duplicate_templates.py`. A dHash score below
   0.95 still needs a human look — description-embedding similarity catches
   same-meme-different-photo duplicates that dHash misses.
2. **`USE_WHEN` entry** in `backend/nlp/intent_router.py`. House style, no
   exceptions: a CAPS-label summary, exactly ONE short "E.g." example, and
   explicit "NOT for X (use Y)" cross-references naming the specific
   templates it will be confused with. One example is a token-budget rule:
   every candidate's entry is sent with every pick, a pick is already close
   to 3000 tokens, and Groq's free tier allows 8000 a minute. What a second
   example does to accuracy is unmeasured. An earlier figure (75% → 67%)
   came from runs that mixed two different prompts and does not stand.
3. **Layout** in `backend/image_processing/template_configs.py`. Optional for
   static templates (falls back to `DEFAULT_BOXES`), but **mandatory for GIF
   templates** — without an explicit entry, `is_gif` defaults to False and
   the animation is silently flattened.
4. **Re-run** `python backend/scripts/precompute_template_embeddings.py`.
   Only re-embeds changed entries. Commit the updated
   `backend/data/template_embeddings.json`.
5. **Seed and verify**: for GIFs, `python scripts/seed_gif_templates.py`.
   Confirm the id appears in `list_template_ids()`, then run one real RAG
   query to confirm the new template surfaces for a well-matched prompt.

After the change, run `/eval-run` to confirm final-pick accuracy hasn't
regressed against the golden set.
