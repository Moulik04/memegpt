#!/usr/bin/env bash
# Send one canned chat to a backend and fail unless the router actually routed.
#
# A canned fallback meme is still a 200 with a rendered image, so checking the
# status code proves nothing about the router. This reads the `fallback` flag on
# the chat stream's `done` event and fails when it is true or missing.
#
# One retry after a pause, so a single rate-limit blip does not block a deploy.
# A second consecutive fallback is treated as real.
#
# A backend that shares a secret with the frontend's server only makes memes
# for requests that server vouched for. Given the same secret, this vouches
# for itself the way that server does. Without it the request goes as is,
# which is right for a backend that has no secret configured.
#
# Usage: scripts/smoke_chat.sh <base-url>
# Env:   SMOKE_RETRY_DELAY    seconds to wait before the retry (default 30)
#        PROXY_SHARED_SECRET  the backend's shared secret, if it has one
set -uo pipefail

BASE_URL="${1:?usage: smoke_chat.sh <base-url>}"
RETRY_DELAY="${SMOKE_RETRY_DELAY:-30}"
MESSAGE="when the tests pass locally but fail in CI"

# 192.0.2.1 is reserved for documentation, so it is never a real visitor's.
VOUCH=()
if [ -n "${PROXY_SHARED_SECRET:-}" ]; then
  VOUCH=(-H "X-MemeGPT-Proxy-Secret: ${PROXY_SHARED_SECRET}" -H 'X-MemeGPT-Client-Address: 192.0.2.1')
fi

attempt() {
  local stream done fallback
  stream=$(curl -sS -N --max-time 60 -X POST "${BASE_URL%/}/chat/" \
    -H 'Content-Type: application/json' \
    -H 'X-MemeGPT-User: smoke-test' \
    ${VOUCH[@]+"${VOUCH[@]}"} \
    -d "$(jq -nc --arg m "${MESSAGE}" '{message: $m}')") || { echo "request failed"; return 1; }

  done=$(printf '%s\n' "${stream}" | sed -n 's/^data: //p' | jq -c 'select(.type == "done")' | head -n1)
  if [ -z "${done}" ]; then
    echo "no done event in the stream"
    return 1
  fi

  fallback=$(jq -r '.fallback' <<< "${done}")
  if [ "${fallback}" = "null" ]; then
    echo "done event has no fallback flag"
    return 1
  fi
  if [ "${fallback}" != "false" ]; then
    echo "router returned its canned fallback (template=$(jq -r '.template_used' <<< "${done}"))"
    return 1
  fi

  echo "router routed (template=$(jq -r '.template_used' <<< "${done}"))"
}

if result=$(attempt); then
  echo "${result}"
  exit 0
fi
echo "attempt 1 failed: ${result}; retrying in ${RETRY_DELAY}s"
sleep "${RETRY_DELAY}"

if result=$(attempt); then
  echo "${result}"
  exit 0
fi
echo "::error::chat smoke test failed twice: ${result}"
exit 1
