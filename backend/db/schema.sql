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
-- messages (Growth Phase H, Stage 3) is a third, narrower exception:
-- message content is stored, but ONLY for signed-in users with an active
-- persisted conversation — anonymous use is completely unaffected.

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

-- Growth Phase H, Stage 3 — persisted chat history (signed-in only).
-- conversations.id is a server-generated uuid, deliberately never the
-- client-correlation `conversation_id` string every ChatRequest/LoreRequest
-- already carries (that string has no server-side registry or ownership
-- concept — see CLAUDE.md's "Growth Phase H" section for the reasoning).
-- Every ownership-sensitive read/write in db/__init__.py pairs this id with
-- user_id (`WHERE id = $1 AND user_id = $2`), never trusting a bare id.
--
-- PRIVACY NOTE: messages.content is a deliberate, explicit exception to
-- this file's "never store situation/dump text" rule at the top — see
-- memegpt-growth-master-prompt.md's Phase H section. Only ever written for
-- signed-in users with an active conversation; anonymous use is completely
-- unaffected (routers/chat.py never calls insert_message without both a
-- verified user_id and an owned conversation_row_id).
CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    title text,
    surface text NOT NULL DEFAULT 'chat',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- meme_id (not a new column on memes) carries the meme<->chat link — memes
-- is shared across anon/signed-in/Discord/Arc and shouldn't grow a
-- signed-in-only column; messages is signed-in-only by construction.
CREATE TABLE IF NOT EXISTS messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    meme_id text REFERENCES memes(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id, created_at);

-- Growth Phase H, Stage 4 — per-chat delete cascade. lore_lexicon.terms
-- (the flat jsonb cache every reader — fetch_lexicon, parse_intent,
-- fetch_personalization — already uses) stays the source of truth for
-- READS, unchanged. This table is the new source of truth for WRITES,
-- letting a per-chat delete find and remove exactly the terms one
-- conversation contributed, then re-derive the cache. Only ever populated
-- for signed-in, conversation-attributed extractions (nlp/lexicon.py) —
-- anonymous schedule_lexicon_extraction calls never reach it, still only
-- writing the flat jsonb cache exactly as Phase C shipped.
-- ON DELETE SET NULL (not CASCADE): unwind_conversation_contribution()
-- explicitly deletes the matching rows itself, before deleting the
-- conversation — relying on cascade here would null conversation_id out
-- from under that explicit DELETE's WHERE clause instead of removing the
-- rows. SET NULL is just the safe default for any row this codepath
-- doesn't reach (there shouldn't be any, but never orphan-reference a
-- deleted conversation either way).
CREATE TABLE IF NOT EXISTS lore_lexicon_terms (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    term text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lore_lexicon_terms_user_id ON lore_lexicon_terms(user_id);
CREATE INDEX IF NOT EXISTS idx_lore_lexicon_terms_conversation_id ON lore_lexicon_terms(conversation_id);
