#!/usr/bin/env bash
# Block Python/pytest invocations that could write to production.
set -euo pipefail

CMD=$(jq -r '.tool_input.command // ""')

# Not a Python-ish run? Allow.
echo "$CMD" | grep -qE '(^|[[:space:]/])(python3?|pytest|uvicorn)([[:space:]]|$)' || exit 0

# Already going through the wrapper, or already blanking creds? Allow.
echo "$CMD" | grep -qE '(verify_safe\.sh|R2_ACCOUNT_ID=|DATABASE_URL=)' && exit 0

# Real creds present in the ambient env file? Block.
if grep -qE '^(R2_ACCESS_KEY_ID|DATABASE_URL|SUPABASE_URL)=.+' backend/.env 2>/dev/null; then
  echo "Blocked: backend/.env holds live credentials and this command does not blank them. Use ./scripts/verify_safe.sh <command>, or state explicitly which single credential you need and why." >&2
  exit 2
fi

exit 0
