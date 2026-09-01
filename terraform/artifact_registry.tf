resource "google_artifact_registry_repository" "backend" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for the ${var.service_name} Cloud Run service."

  # Phase 3's ci-deploy.yml pushes one new, uniquely-tagged image
  # ("sha-<7-char-sha>") on every merge to main — unbounded, monotonic
  # growth without this. Artifact Registry evaluates KEEP policies before
  # DELETE ones, so the most-recent 15 sha-tagged images are always
  # protected regardless of age; anything older AND beyond that window
  # gets deleted. A first version of this scoped the only DELETE policy to
  # `tag_state = "UNTAGGED"` — verified against live state that this
  # never matches anything CI pushes (every CI image is tagged, uniquely,
  # forever), so growth stayed unbounded despite the policy existing.
  # Kept the untagged-cleanup rule too, for genuinely orphaned layers from
  # this repo's earlier manual-push history ("phase2-manual"/"latest"),
  # with a short grace period so an in-flight pull can't race a deletion.
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 15
    }
  }

  cleanup_policies {
    id     = "delete-old-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "86400s" # 1 day
    }
  }

  cleanup_policies {
    id     = "delete-old-ci-images"
    action = "DELETE"
    condition {
      tag_state    = "TAGGED"
      tag_prefixes = ["sha-"]
      older_than   = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.apis]
}
