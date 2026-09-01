resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Trusts GitHub's OIDC tokens for this repo's Actions workflows — no long-lived key ever leaves GCP."

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Scoped to exactly this repo — no other GitHub repo's tokens can assume
  # the CI service account below, even within the same GitHub org.
  attribute_condition = "assertion.repository == \"Moulik04/memegpt\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "ci_deploy" {
  account_id   = "${var.service_name}-ci"
  display_name = "${var.service_name} CI/CD deploy identity"
  description  = "Used only by GitHub Actions (via Workload Identity Federation, no key material) to build/push images, write Terraform state, and deploy Cloud Run revisions."

  depends_on = [google_project_service.apis]
}

# Lets the GitHub-repo-scoped WIF principal impersonate this service account.
resource "google_service_account_iam_member" "ci_deploy_wif_binding" {
  service_account_id = google_service_account.ci_deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/Moulik04/memegpt"
}

# Terraform refreshes EVERY resource in state before computing any plan,
# not just what a given apply changes — so the CI SA needs read access to
# every resource type this state manages (WIF pool/provider, secrets,
# service accounts, IAM bindings, project API enablement, ...), not just
# the ones it's meant to modify. Discovered the hard way: a real deploy
# failed on `google_project_service.apis[...]` refresh with a bare
# `serviceusage.services.list` 403 — none of the narrower roles below
# cover that, or the several other read-only resource types in this same
# state file. Rather than add a project-level viewer-equivalent role per
# resource type one real-failure at a time, granting the one standard
# read-only role built for exactly this ("see everything, change
# nothing") — paired with the specific, narrow WRITE grants below, which
# are what actually bound what this identity can change.
resource "google_project_iam_member" "ci_deploy_viewer" {
  project = var.project_id
  role    = "roles/viewer"
  member  = "serviceAccount:${google_service_account.ci_deploy.email}"
}

# Push/pull images.
resource "google_project_iam_member" "ci_deploy_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.ci_deploy.email}"
}

# Create/update Cloud Run revisions and read service status for smoke tests.
resource "google_project_iam_member" "ci_deploy_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.ci_deploy.email}"
}

# Deploying a revision that runs AS the runtime SA requires this — without
# it, Cloud Run refuses to attach google_service_account.cloud_run_runtime
# to a new revision on the CI SA's behalf.
resource "google_service_account_iam_member" "ci_deploy_runtime_sa_user" {
  service_account_id = google_service_account.cloud_run_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci_deploy.email}"
}

# Terraform state lives in a specific GCS bucket (Phase 1, deliberately kept
# out of every .tf file via partial backend config). IAM on a *specific*
# bucket has no way to reference that indirection — the bucket name is
# unavoidably literal here, scoped to exactly this one bucket, not a
# project-wide storage role.
resource "google_storage_bucket_iam_member" "ci_deploy_state_access" {
  bucket = "memegpt-infra-68502-tfstate"
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ci_deploy.email}"
}
