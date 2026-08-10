---
name: safe-verify
description: Run local verification with all real credentials blanked. Use before running any script or test that could write to R2, Postgres, or an external API.
allowed-tools: Bash(${CLAUDE_PROJECT_DIR}/scripts/verify_safe.sh *)
---

`backend/.env` holds live production credentials. Running verification code
that calls `save_meme()`, `db.insert_*`, or any provider client with those
loaded writes real data to production. This has happened twice on this
project.

Never run verification code with the ambient environment. Always:

    ./scripts/verify_safe.sh <command>

The wrapper blanks `R2_*`, `DATABASE_URL`, `SUPABASE_*`, `GEMINI_API_KEY`,
`GROQ_API_KEY`, and `DISCORD_*` before exec'ing the command. If a check
genuinely requires a real credential (an end-to-end R2 verification, for
example), say so explicitly, name which single credential is needed and
why, and get a go-ahead before running it — don't just drop the wrapper.
