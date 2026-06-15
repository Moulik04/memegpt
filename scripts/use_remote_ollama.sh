#!/usr/bin/env bash
# Switch OLLAMA_HOST in docker-compose.yml backend environment to a remote URL.
# Usage: ./scripts/use_remote_ollama.sh <url>
# Example: ./scripts/use_remote_ollama.sh http://2.tcp.ngrok.io:12345
#          ./scripts/use_remote_ollama.sh http://localhost:11434   # revert to local

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <ollama-url>"
    echo "  Colab ngrok:  http://2.tcp.ngrok.io:XXXXX"
    echo "  Bridges2 SSH: http://localhost:11434  (after ssh -L 11434:...)"
    echo "  Local native: http://host.docker.internal:11434"
    exit 1
fi

URL="$1"
COMPOSE="$(dirname "$0")/../docker-compose.yml"

sed -i.bak \
    "s|OLLAMA_HOST: .*|OLLAMA_HOST: $URL|g" \
    "$COMPOSE"

echo "Updated OLLAMA_HOST → $URL"
echo "Recreating backend container (restart doesn't apply env changes)..."
docker compose up -d backend
echo "Done."
