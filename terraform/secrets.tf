resource "google_secret_manager_secret" "backend" {
  for_each = toset(var.secret_names)

  secret_id = each.value
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    prevent_destroy = true
  }
}
