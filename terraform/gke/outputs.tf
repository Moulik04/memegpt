output "cluster_name" {
  description = "Name of the GKE Autopilot cluster — used by `gcloud container clusters get-credentials`."
  value       = google_container_cluster.verify.name
}

output "cluster_location" {
  description = "Region the cluster was created in — used by `gcloud container clusters get-credentials`."
  value       = google_container_cluster.verify.location
}
