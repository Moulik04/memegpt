resource "google_artifact_registry_repository" "backend" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for the ${var.service_name} Cloud Run service."

  depends_on = [google_project_service.apis]
}
