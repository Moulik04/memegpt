locals {
  required_apis = [
    "container.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project = var.project_id
  service = each.value

  # Matches the main stack's convention (terraform/main.tf) — never let
  # `terraform destroy` disable a project-wide API something else might
  # depend on.
  disable_on_destroy = false
}

resource "google_container_cluster" "verify" {
  name     = var.cluster_name
  location = var.region

  enable_autopilot = true

  # Autopilot clusters default this to true (confirmed against the real
  # provider v5.45.2 schema), which blocks `terraform destroy` outright.
  # This cluster exists for a single verification session and must be
  # destroy-able on demand.
  deletion_protection = false

  # Autopilot requires a VPC-native cluster; an empty block accepts GKE's
  # own automatic secondary-range allocation.
  ip_allocation_policy {}

  depends_on = [google_project_service.apis]
}
