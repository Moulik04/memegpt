terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Bucket and prefix are supplied at `terraform init` time via
  # -backend-config=backend.hcl (gitignored, real values — see
  # backend.hcl.example and README.md). Left empty here so no
  # project-specific value is ever committed.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
