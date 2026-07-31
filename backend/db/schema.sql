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

CREATE TABLE IF NOT EXISTS lore_lexicon (
    anon_user_id text PRIMARY KEY,
    terms jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_meme_id ON feedback(meme_id);
CREATE INDEX IF NOT EXISTS idx_feedback_anon_user_id ON feedback(anon_user_id);
CREATE INDEX IF NOT EXISTS idx_memes_anon_user_id ON memes(anon_user_id);
