resource "google_artifact_registry_repository" "backend" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for the ${var.service_name} Cloud Run service."

  # Phase 3's ci-deploy.yml pushes one new image on every merge to main —
  # unbounded, monotonic growth without this. Keep enough tagged versions
  # for real rollback investigation; delete untagged layers (left behind
  # by re-pushes under the same tag, e.g. this repo's own history of
  # rebuilding "phase2-manual"/"latest"-style tags) after a short grace
  # period rather than immediately, so an in-flight pull can't race a
  # deletion.
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

  depends_on = [google_project_service.apis]
}
