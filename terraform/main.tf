locals {
  required_apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iamcredentials.googleapis.com", # NEW — needed for WIF's short-lived credential exchange
    "sts.googleapis.com",            # NEW — Security Token Service, WIF's OIDC token exchange
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project = var.project_id
  service = each.value

  # Never let `terraform destroy` disable project-wide APIs — this phase's
  # destroy/apply round-trip test (Task 6) should be fast and side-effect
  # free, not silently disable APIs other things in the project may use.
  disable_on_destroy = false
}
