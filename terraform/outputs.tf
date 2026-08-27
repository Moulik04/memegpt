output "artifact_registry_repository" {
  description = "Full Artifact Registry repository path for `docker push` / CI image tags."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}"
}

output "cloud_run_runtime_service_account_email" {
  description = "Service account Phase 2's Cloud Run service should run as."
  value       = google_service_account.cloud_run_runtime.email
}

output "secret_ids" {
  description = "Secret Manager secret ids provisioned as empty containers — no values."
  value       = [for s in google_secret_manager_secret.backend : s.secret_id]
}
