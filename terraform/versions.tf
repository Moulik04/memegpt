terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    # google-beta pinned to the same 5.x line as google, above — used only
    # by google_cloud_run_v2_service.backend (cloud_run.tf) for its
    # `empty_dir` in-memory volumes. That block isn't in the GA `google`
    # provider until the 6.x major line; bumping the primary `google`
    # provider to 6.x was avoided here since it would re-evaluate all 33
    # already-applied Phase 1 resources against a new major provider
    # version — out of scope for a 2-resource Phase 2 task. Revisit by
    # dropping this alias once the whole stack moves to google 6.x.
    google-beta = {
      source  = "hashicorp/google-beta"
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

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
