#!/usr/bin/env bash
# Show what the live Cloud Run service is running, without dumping its env.
#
#   scripts/cloudrun_status.sh [SERVICE] [REGION]
#
# Prints the serving revision(s), traffic split, image digest, and the
# service's environment: values only for an allowlist of non-secret config
# (model names, provider, limits), names only for everything else, and the
# secret name + version for Secret Manager references. Raw `gcloud run ...
# describe` output is blocked by the Claude Code hook because a literal
# secret in the env would be printed with the rest.
set -euo pipefail

service="${1:-memegpt-backend}"
region="${2:-us-central1}"

gcloud run services describe "$service" --region="$region" --format=json | jq -r '
  def safe: test("(_MODEL$|^LLM_PROVIDER$|^CORS_|^LOG_LEVEL$|^DEBUG$|^MAX_|_ENABLED$|^OLLAMA_|^CHROMA_)");
  .status as $s
  | .spec.template.spec.containers[0] as $c
  | "service:   \(.metadata.name)  \(.status.url)",
    "latest:    \($s.latestReadyRevisionName)",
    ($s.traffic[] | "traffic:   \(.percent)% -> \(.revisionName // "latest")\(if .tag then " [tag \(.tag)]" else "" end)"),
    "image:     \($c.image | split("@")[1][0:19] // $c.image)",
    "env:",
    ($c.env[]? | if .valueFrom.secretKeyRef
        then "  \(.name)  <- secret \(.valueFrom.secretKeyRef.name):\(.valueFrom.secretKeyRef.key)"
        elif (.name | safe) then "  \(.name)=\(.value)"
        else "  \(.name)  (value hidden)" end)
'
