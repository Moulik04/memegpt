terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Separate state from the main terraform/ stack — own bucket prefix, own
  # state file, so a `terraform destroy` here can never touch the live
  # Cloud Run backend. Bucket/prefix supplied at `terraform init` time via
  # -backend-config=backend.hcl (gitignored) — see backend.hcl.example.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
