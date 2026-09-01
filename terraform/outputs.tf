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

output "cloud_run_url" {
  description = "Live URL of the Cloud Run backend service."
  value       = google_cloud_run_v2_service.backend.uri
}

output "wif_provider_name" {
  description = "Full WIF provider resource name — used as GitHub Actions' workload_identity_provider input."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account_email" {
  description = "CI deploy service account email — used as GitHub Actions' service_account input."
  value       = google_service_account.ci_deploy.email
}

output "cloud_run_image_digest" {
  description = "The image digest currently applied to the Cloud Run service (without the sha256: prefix) — lets a PR's terraform plan reuse the live value via `terraform output -raw cloud_run_image_digest` instead of a placeholder."
  value       = var.cloud_run_image_digest
}
