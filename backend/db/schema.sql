-- Growth Phase B — Postgres schema. Applied idempotently on first pool
-- connection (see pool.py's _ensure_schema) — no Alembic, matching this
-- repo's "no redesign, keep it simple" pattern for a 3-table schema.
--
-- PRIVACY RULE (confirmed with user): memes and feedback never store
-- situation text, dump text, or captions — ids and metadata only.
-- few_shot_examples is a deliberate exception — storing
-- (user_message, template_id, texts) is its entire purpose, replacing an
-- already-existing ChromaDB store with the same content, not new exposure.
-- lore_lexicon (Growth Phase C) is the other deliberate exception: it
-- stores short LLM-extracted phrases (names/nicknames/running jokes), never
-- raw dump text, and only when the user opts in — see nlp/lexicon.py.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS memes (
    id text PRIMARY KEY,
    url text NOT NULL,
    template_id text,
    mode text NOT NULL,
    anon_user_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meme_id text REFERENCES memes(id),
    rating text NOT NULL,
    conversation_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS few_shot_examples (
    id text PRIMARY KEY,
    user_message text NOT NULL,
    template_id text NOT NULL,
    texts jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Growth Phase C additions.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS anon_user_id text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS template_id text;

-- Growth Phase D: which public surface generated this meme ("chat"/"lore"),
-- stamped by the endpoint that served it — powers Arc's Chat-vs-Lore split.
-- NULL for pre-Phase-D rows and for Arc share cards themselves.
ALTER TABLE memes ADD COLUMN IF NOT EXISTS surface text;

CREATE TABLE IF NOT EXISTS lore_lexicon (
    anon_user_id text PRIMARY KEY,
    terms jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_meme_id ON feedback(meme_id);
CREATE INDEX IF NOT EXISTS idx_feedback_anon_user_id ON feedback(anon_user_id);
CREATE INDEX IF NOT EXISTS idx_memes_anon_user_id ON memes(anon_user_id);

-- Growth Phase H, Stage 2 — signed-in personalization, layered alongside
-- (never replacing) the anon_user_id columns above. user_id is Supabase's
-- `sub` claim (opaque text, no FK — auth.users lives in Supabase's own
-- managed schema, not this database). Once signed in, every personalization
-- read keys EXCLUSIVELY off user_id (never unions with anon_user_id, which
-- would double-count in humor-profile aggregation) — the anon->user link
-- happens once, explicitly, via migrate_anon_data_to_user().
ALTER TABLE memes ADD COLUMN IF NOT EXISTS user_id text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS user_id text;
CREATE INDEX IF NOT EXISTS idx_memes_user_id ON memes(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);

-- lore_lexicon's PRIMARY KEY is anon_user_id (NOT NULL by the PK
-- constraint itself), and the frontend always sends the anon header
-- regardless of sign-in state (lib/identity.ts never stops sending it), so
-- every real lexicon row is still reachable by anon_user_id in practice.
-- user_id is a plain nullable column (no unique constraint — a partial
-- unique index would conflict with the existing PK-based upsert target)
-- stamped onto that same anon-keyed row by migrate_anon_data_to_user(). A
-- user who has linked more than one browser could in principle have more
-- than one lexicon row tagged with their user_id; fetch_lexicon(user_id=...)
-- picks the most recently updated one — an accepted simplification for a
-- feature that's already documented as "a light nudge, never a hard rule."
ALTER TABLE lore_lexicon ADD COLUMN IF NOT EXISTS user_id text;
CREATE INDEX IF NOT EXISTS idx_lore_lexicon_user_id ON lore_lexicon(user_id);
