#!/usr/bin/env bash
# Run a command with all real credentials blanked.
#
# Variable names match backend/config.py's actual Settings fields — R2_BUCKET
# and R2_PUBLIC_BASE_URL, not R2_BUCKET_NAME/R2_PUBLIC_URL (an earlier draft
# of this script used the wrong names, which would have silently failed to
# blank the real R2 credentials). GROQ_API_KEY is included since it's a live
# key used for the primary production LLM calls.
set -euo pipefail
env \
  R2_ACCOUNT_ID= R2_ACCESS_KEY_ID= R2_SECRET_ACCESS_KEY= \
  R2_BUCKET= R2_PUBLIC_BASE_URL= \
  DATABASE_URL= \
  SUPABASE_URL= SUPABASE_ANON_KEY= \
  GEMINI_API_KEY= \
  GROQ_API_KEY= \
  DISCORD_BOT_TOKEN= DISCORD_WORKER_SHARED_SECRET= \
  "$@"
