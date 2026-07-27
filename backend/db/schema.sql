-- Growth Phase B — Postgres schema. Applied idempotently on first pool
-- connection (see pool.py's _ensure_schema) — no Alembic, matching this
-- repo's "no redesign, keep it simple" pattern for a 3-table schema.
--
-- PRIVACY RULE (confirmed with user): memes and feedback never store
-- situation text, dump text, or captions — ids and metadata only.
-- few_shot_examples is the deliberate exception — storing
-- (user_message, template_id, texts) is its entire purpose, replacing an
-- already-existing ChromaDB store with the same content, not new exposure.

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

CREATE INDEX IF NOT EXISTS idx_feedback_meme_id ON feedback(meme_id);
