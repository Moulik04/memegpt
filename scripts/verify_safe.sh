#!/usr/bin/env bash
# Run a command with every credential that can write to shared storage or an
# external service blanked.
#
# Blanked: Postgres (DATABASE_URL), R2 storage (R2_*), Gemini (GEMINI_API_KEY,
# so local runs use the local embedding model and spend no quota), and the
# Discord bot credentials.
#
# Deliberately left alone:
#   SUPABASE_URL / SUPABASE_ANON_KEY  public by design (they ship to every
#                                     browser), and blanking them breaks
#                                     local sign-in.
#   GROQ_API_KEY                      the one external credential a local run
#                                     is expected to use. Without it chat
#                                     quietly falls back to Ollama and Make
#                                     captions and uploads are refused.
#
# Variable names match backend/config.py's actual Settings fields — R2_BUCKET
# and R2_PUBLIC_BASE_URL, not R2_BUCKET_NAME/R2_PUBLIC_URL (an earlier draft
# of this script used the wrong names, which would have silently failed to
# blank the real R2 credentials).
set -euo pipefail
env \
  R2_ACCOUNT_ID= R2_ACCESS_KEY_ID= R2_SECRET_ACCESS_KEY= \
  R2_BUCKET= R2_PUBLIC_BASE_URL= \
  DATABASE_URL= \
  GEMINI_API_KEY= \
  DISCORD_BOT_TOKEN= DISCORD_WORKER_SHARED_SECRET= \
  DISCORD_APP_ID= DISCORD_PUBLIC_KEY= \
  "$@"
