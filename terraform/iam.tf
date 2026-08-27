resource "google_service_account" "cloud_run_runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "${var.service_name} Cloud Run runtime identity"
  description  = "Runtime identity for the Cloud Run service. Least-privilege: read access to this project's own Secret Manager secrets only, granted per-secret in secrets.tf — nothing else."

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "runtime_secret_access" {
  for_each = google_secret_manager_secret.backend

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_runtime.email}"
}
