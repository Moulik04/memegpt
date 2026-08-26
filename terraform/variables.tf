variable "project_id" {
  description = "GCP project ID this stack provisions into."
  type        = string
}

variable "region" {
  description = "GCP region for all regional resources (Cloud Run, Artifact Registry)."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Base name used for the Cloud Run service, Artifact Registry repo, and related resources."
  type        = string
  default     = "memegpt-backend"
}

variable "secret_names" {
  description = "Secret Manager secret ids to provision as empty containers. Values are never set by Terraform — see terraform/README.md for how to add them after `apply`."
  type        = list(string)
  default = [
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
  ]
}

# Cloud Run resource sizing — declared here per CLOUD_MIGRATION_MASTER.md
# Phase 1 item 4 ("variables for region, service name, and resource
# sizing"). Not consumed by anything in Phase 1; Phase 2's cloud_run.tf
# reads these.
variable "cloud_run_cpu" {
  description = "vCPU allocated to the Cloud Run service (consumed starting Phase 2)."
  type        = string
  default     = "1"
}

variable "cloud_run_memory" {
  description = "Memory allocated to the Cloud Run service (consumed starting Phase 2)."
  type        = string
  default     = "512Mi"
}

variable "cloud_run_min_instances" {
  description = "Minimum Cloud Run instances (consumed starting Phase 2). 0 = scales to zero, no idle cost."
  type        = number
  default     = 0
}

variable "cloud_run_max_instances" {
  description = "Maximum Cloud Run instances (consumed starting Phase 2) — a cost ceiling against runaway traffic."
  type        = number
  default     = 2
}
