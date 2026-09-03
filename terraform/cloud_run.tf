resource "google_cloud_run_v2_service" "backend" {
  provider = google-beta # empty_dir in-memory volumes below aren't in the GA
  # google provider's 5.x line (only 6.x+) — see versions.tf's note by the
  # google-beta provider block. deletion_protection isn't available in
  # google-beta 5.x either, so it's omitted; the 5.x provider has no
  # Terraform-side destroy guard for this resource either way, so omitting
  # it doesn't change destroyability versus the brief's explicit `false`.

  name     = var.service_name
  location = var.region
  project  = var.project_id

  # Service-level scaling — distinct from (and in addition to) the
  # per-revision `template.scaling` block below. The google-beta provider's
  # `google_cloud_run_v2_service` schema has both: this top-level block only
  # carries `min_instance_count` (floor shared across all revisions
  # receiving traffic), while `template.scaling` carries both min and max
  # for the revision being created. The live Cloud Run API always reports a
  # value for the service-level `scaling.minInstanceCount` (0 by default);
  # leaving this block out of config left Terraform perpetually planning to
  # null it back out on every `plan`/`apply`. Setting it explicitly here,
  # mirrored to the same variable as the per-revision floor, makes `plan`
  # converge to "No changes".
  scaling {
    min_instance_count = var.cloud_run_min_instances
  }

  template {
    # Explicit, non-default runtime identity — Phase 1's whole least-privilege
    # story (per-secret secretAccessor, nothing else) only holds if this is
    # set. Omitting it silently falls back to the project's default compute
    # service account, which already carries roles/editor.
    service_account = google_service_account.cloud_run_runtime.email

    scaling {
      min_instance_count = var.cloud_run_min_instances
      max_instance_count = var.cloud_run_max_instances
    }

    timeout                          = "300s" # covers a full multi-meme Lore batch, not just one meme
    max_instance_request_concurrency = 20

    containers {
      # Pinned to a specific digest, not the `:phase2-manual` tag. Terraform
      # tracks the literal image string in state — if a mutable tag gets
      # repushed to point at new content, the string here doesn't change, so
      # a bare `terraform apply` reports "No changes" and the stale revision
      # stays live even though the tag now resolves to something different.
      # (This is exactly what happened during this task: the tag was
      # repushed after an arm64/amd64 platform bug, and re-applying against
      # the unchanged tag string would have silently kept the broken
      # revision serving traffic.) Pinning to a digest is what actually
      # guarantees a new `terraform apply` picks up new image content — this
      # is standard Cloud-Run-via-Terraform practice, not a one-off patch.
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}/${var.service_name}@sha256:${var.cloud_run_image_digest}"

      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
      }

      env {
        name  = "LLM_PROVIDER"
        value = "groq"
      }
      env {
        name  = "GROQ_MODEL"
        value = "qwen/qwen3.6-27b"
      }
      env {
        name  = "GEMINI_EMBEDDING_MODEL"
        value = "gemini-embedding-2"
      }
      env {
        name  = "CORS_ALLOW_ALL_ORIGINS"
        value = "true"
      }
      env {
        # Pins the HTTP semantic-convention mode opentelemetry-instrumentation-
        # asgi/-fastapi use, rather than inheriting whatever the installed
        # library's unset-env-var default resolves to. observability/dashboard.json
        # and alert-error-rate.json hardcode the OLD (pre-stable) convention's
        # metric name and label (http_server_duration_milliseconds_count,
        # http_status_code) — "http/dup" guarantees those keep being emitted
        # (confirmed by reading the installed opentelemetry-instrumentation
        # 0.65b0 source: it separately emits an old-convention histogram
        # whenever the resolved mode isn't exactly "http", and "http/dup" also
        # emits the new-convention series alongside, at negligible extra cost)
        # even if a future dependency upgrade changes what leaving this unset
        # means. There is no documented value that means "old-only, pinned" —
        # the two documented tokens are "http" (switches fully to the new
        # convention, which would silently break the dashboard/alert) and
        # "http/dup" (both conventions emitted) — so "http/dup" is the
        # explicit, source-confirmed choice that can't regress the existing
        # dashboard/alert.
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "http/dup"
      }
      env {
        name = "GROQ_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GROQ_API_KEY"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GEMINI_API_KEY"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GRAFANA_OTLP_ENDPOINT"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GRAFANA_OTLP_ENDPOINT"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GRAFANA_OTLP_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GRAFANA_OTLP_TOKEN"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "chroma-data"
        mount_path = "/app/data/chroma"
      }
      volume_mounts {
        name       = "static-generated"
        mount_path = "/app/static/generated"
      }
    }

    # In-memory, per-instance, ephemeral — solves Cloud Run's read-only
    # container filesystem at zero extra cost. NOT durable across instances
    # or cold starts; see CLOUD_MIGRATION_MASTER.md's "problem the spec
    # didn't name" note. Real cross-instance durability is Cloudflare R2
    # (already supported by storage/save_meme(), not turned on this phase).
    volumes {
      name = "chroma-data"
      empty_dir {
        medium     = "MEMORY"
        size_limit = "64Mi"
      }
    }
    volumes {
      name = "static-generated"
      empty_dir {
        medium     = "MEMORY"
        size_limit = "64Mi"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_secret_access]
}

# Public ingress — this phase is pre-cutover verification, curled directly,
# not yet linked from frontend/. Matches Render's current publicly-reachable
# setup. Revisit at actual cutover if auth in front of Cloud Run is wanted.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
