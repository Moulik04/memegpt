#!/usr/bin/env bash
# Report whether a variable is set, and how long its value is. Never the value.
#
#   scripts/env_check.sh VAR          check this shell's environment
#   scripts/env_check.sh VAR FILE     check a dotenv-style file
#
# Prints exactly "set (N chars)" or "unset". An empty value counts as unset.
# Exit status: 0 set, 1 unset, 2 bad usage.
#
# The Claude Code hook (.claude/hooks/guard_secrets.py) lets this script
# through even when FILE is a secrets file, so keep it incapable of echoing
# a value: nothing below prints anything derived from the value except its
# length.
set -u

var="${1:-}"
file="${2:-}"

if [[ ! "$var" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || [[ $# -gt 2 ]]; then
  echo "usage: scripts/env_check.sh VAR [FILE]" >&2
  exit 2
fi

if [[ -n "$file" ]]; then
  if [[ ! -r "$file" ]]; then
    echo "env_check: cannot read $file" >&2
    echo "unset"
    exit 1
  fi
  # Last assignment wins, as it does when the file is sourced. Handles an
  # optional `export`, CRLF line endings, matching surrounding quotes, and a
  # trailing " # comment" on unquoted values.
  n=$(awk -v v="$var" '
    { sub(/\r$/, "") }
    $0 ~ ("^[[:space:]]*(export[[:space:]]+)?" v "=") {
      val = $0
      sub("^[[:space:]]*(export[[:space:]]+)?" v "=", "", val)
      found = 1
      last = val
    }
    END {
      if (!found) { print 0; exit }
      val = last
      if (val ~ /^"/)        { sub(/^"/, "", val); sub(/"[[:space:]]*(#.*)?$/, "", val) }
      else if (val ~ /^\047/) { sub(/^\047/, "", val); sub(/\047[[:space:]]*(#.*)?$/, "", val) }
      else                   { sub(/[[:space:]]+#.*$/, "", val); sub(/[[:space:]]+$/, "", val) }
      print length(val)
    }' "$file")
else
  val="${!var-}"
  n=${#val}
  unset val
fi

if [[ "${n:-0}" -gt 0 ]]; then
  echo "set ($n chars)"
  exit 0
fi
echo "unset"
exit 1
