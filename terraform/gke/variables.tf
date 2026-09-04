variable "project_id" {
  description = "GCP project ID this cluster provisions into — same project as the main terraform/ stack."
  type        = string
}

variable "region" {
  description = "GCP region for the cluster and its default node location."
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "Name of the GKE Autopilot cluster."
  type        = string
  default     = "memegpt-verify"
}
