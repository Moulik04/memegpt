# Cloud Migration Phase 1 — Terraform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the GCP project and the Terraform-managed foundation (state backend, enabled APIs, Artifact Registry, a least-privilege Cloud Run runtime service account, and empty Secret Manager containers for every credential the backend needs) that Phase 2's Cloud Run service will build on.

**Architecture:** One root Terraform module (`terraform/`) with GCS remote state (versioned, locked), a `google` provider pinned to the project created in this phase, and resources split by concern into separate `.tf` files (APIs, Artifact Registry, IAM, Secret Manager, outputs). No Cloud Run service and no secret *values* are created in this phase — those are Phase 2 and a manual `gcloud secrets versions add` respectively.

**Tech Stack:** Terraform >= 1.7, `hashicorp/google` provider ~> 5.0, GCP (Cloud Run API, Artifact Registry, Secret Manager, Cloud Monitoring, IAM), `gcloud` CLI.

**Spec:** [CLOUD_MIGRATION_MASTER.md](../../../CLOUD_MIGRATION_MASTER.md) — this plan implements that spec's "Phase 1 — Terraform foundation" section only.

## Global Constraints

- Plan before code, every phase — this plan itself is the Phase 1 checkpoint; get explicit approval before Task 1 starts.
- **The live demo must not break.** This phase touches nothing Render-facing — it only provisions new GCP resources. No risk to the running service.
- **Hard cost ceiling: $10/month steady state.** Projected cost of everything in this phase: **~$0.00/month.** Enabling APIs is free; the Artifact Registry repo and Secret Manager containers cost nothing until images/versions are pushed into them (Phase 2); the GCS state bucket holds a state file of a few KB, inside GCS's always-free regional storage tier.
- Secrets never enter Terraform state, `.tf` files, or git. This phase creates Secret Manager *secret containers* only (`google_secret_manager_secret`) — no `google_secret_manager_secret_version` resource appears anywhere in this plan, so no secret value ever reaches Terraform state.
- No hardcoded project IDs anywhere in committed files. `project_id` is a required variable with no default, supplied via a gitignored `terraform.tfvars`; the GCS backend bucket name is supplied via a gitignored `backend.hcl`, not the committed `versions.tf`.
- Verify against real GCP state (`gcloud ... describe/list`), not just `terraform plan` output.
- Update `CLAUDE.md` invariants and `docs/DECISIONS.md` at the end of this phase (Task 6).

---

## File Structure

```
terraform/
├── README.md                  Bootstrap-from-zero doc (Task 6)
├── .gitignore                 terraform/-scoped ignores (Task 2)
├── versions.tf                Terraform + provider version pins, empty `backend "gcs" {}` block (Task 2)
├── variables.tf                project_id/region/service_name/secret_names/cloud_run_* vars (Task 2)
├── terraform.tfvars.example   Template for the gitignored real tfvars (Task 2)
├── backend.hcl.example        Template for the gitignored real backend config (Task 2)
├── main.tf                    google_project_service (API enablement) (Task 3)
├── artifact_registry.tf       google_artifact_registry_repository (Task 4)
├── iam.tf                     google_service_account + per-secret IAM bindings (Task 4)
├── secrets.tf                 google_secret_manager_secret containers (Task 5)
└── outputs.tf                 Artifact Registry path, runtime SA email, secret ids (Task 6)
```

Root `.gitignore` also gains a `terraform/` block (state, `.terraform/`, tfvars, backend config — Task 2).

---

### Task 1: GCP project, CLI tooling, and state bucket bootstrap

**Files:** none yet — this task is entirely CLI setup, no repo changes.

**Interfaces:**
- Produces: an authenticated `gcloud` CLI on this machine (usable non-interactively by later `terraform`/`gcloud` commands run from this session), a GCP project with billing linked, and a versioned GCS bucket for Terraform state. Later tasks assume all three exist.

This task mixes two kinds of steps: ones I (the agent) can run directly, and ones that need your interactive GCP login/billing account — those are called out explicitly.

- [ ] **Step 1: Install Terraform and the gcloud CLI (agent-run)**

```bash
brew install terraform google-cloud-sdk
terraform version   # expect >= 1.7.0
gcloud version
```

- [ ] **Step 2: Authenticate gcloud (you run this — needs your browser)**

```bash
gcloud auth login
gcloud auth application-default login
```

The second command is what lets Terraform (and any `gcloud`/`terraform` command I run later in this session) use your credentials non-interactively — run it even though the first one also opens a browser.

- [ ] **Step 3: Create the GCP project and link billing (you run this — needs your billing account)**

```bash
# Pick a globally-unique project id, e.g. memegpt-prod-<random suffix>
gcloud projects create YOUR_PROJECT_ID --name="MemeGPT"

# List your billing accounts to find the ID to link:
gcloud billing accounts list

gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID

gcloud config set project YOUR_PROJECT_ID
```

- [ ] **Step 4: Enable the one API Terraform itself needs to manage other APIs (you or agent, once project exists)**

```bash
gcloud services enable serviceusage.googleapis.com --project=YOUR_PROJECT_ID
```

Every other API (Cloud Run, Artifact Registry, Secret Manager, Monitoring, IAM, Cloud Resource Manager) is enabled *by Terraform* in Task 3 — this is the one bootstrap exception, since `google_project_service` itself needs Service Usage API already on.

- [ ] **Step 5: Create the versioned GCS state bucket (agent-run, once project id is known)**

```bash
gcloud storage buckets create gs://YOUR_PROJECT_ID-tfstate \
  --project=YOUR_PROJECT_ID \
  --location=us-central1 \
  --uniform-bucket-level-access

gcloud storage buckets update gs://YOUR_PROJECT_ID-tfstate --versioning
```

Versioning is what gives state locking-adjacent safety (recoverable history if state gets corrupted); real locking comes from the GCS backend's native lock support in Task 2's `versions.tf`.

- [ ] **Step 6: Confirm bootstrap**

```bash
gcloud config get-value project              # expect YOUR_PROJECT_ID
gcloud storage buckets describe gs://YOUR_PROJECT_ID-tfstate --format="value(name,versioning.enabled)"
```

Expected: bucket name echoed back, `versioning.enabled: True`.

No commit for this task — nothing in the repo changed yet.

---

### Task 2: Terraform skeleton (versions, variables, gitignore)

**Files:**
- Create: `terraform/versions.tf`
- Create: `terraform/variables.tf`
- Create: `terraform/terraform.tfvars.example`
- Create: `terraform/backend.hcl.example`
- Create: `terraform/.gitignore`
- Modify: `.gitignore` (root)

**Interfaces:**
- Produces: `var.project_id`, `var.region` (default `"us-central1"`), `var.service_name` (default `"memegpt-backend"`), `var.secret_names` (default list of 11 secret ids), `var.cloud_run_cpu`, `var.cloud_run_memory`, `var.cloud_run_min_instances`, `var.cloud_run_max_instances` — every later task and Phase 2 read these by name.

- [ ] **Step 1: Write `terraform/versions.tf`**

```hcl
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
```

- [ ] **Step 2: Write `terraform/variables.tf`**

```hcl
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
```

- [ ] **Step 3: Write `terraform/terraform.tfvars.example`**

```hcl
project_id = "your-gcp-project-id"

# Uncomment to override defaults:
# region       = "us-central1"
# service_name = "memegpt-backend"
```

- [ ] **Step 4: Write `terraform/backend.hcl.example`**

```hcl
bucket = "your-gcp-project-id-tfstate"
prefix = "memegpt-backend"
```

- [ ] **Step 5: Write `terraform/.gitignore`**

```
.terraform/
.terraform.lock.hcl
*.tfstate
*.tfstate.*
terraform.tfvars
backend.hcl
crash.log
crash.*.log
```

- [ ] **Step 6: Add a `terraform/` section to the root `.gitignore`**

Append to `/Users/moulik/Desktop/memegpt/.gitignore`:

```

# Terraform (terraform/ has its own .gitignore too — belt and suspenders
# in case a *.tfvars-style file ever gets created outside that directory)
**/.terraform/
*.tfstate
*.tfstate.*
```

- [ ] **Step 7: Create your real (gitignored) tfvars and backend config**

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
# Edit both files, replacing the placeholder project id with the real one from Task 1.
```

- [ ] **Step 8: Init and validate**

```bash
cd terraform
terraform init -backend-config=backend.hcl
terraform validate
```

Expected: `terraform init` reports `Successfully configured the backend "gcs"!`, `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 9: Commit**

```bash
git add terraform/versions.tf terraform/variables.tf terraform/terraform.tfvars.example \
        terraform/backend.hcl.example terraform/.gitignore .gitignore
git commit -m "infra: add Terraform skeleton (state backend, core variables)"
```

(`terraform.tfvars`, `backend.hcl`, and `.terraform/` stay untracked — confirm with `git status` before committing that only the files above are staged.)

---

### Task 3: Enable required GCP APIs

**Files:**
- Create: `terraform/main.tf`

**Interfaces:**
- Consumes: `var.project_id` (Task 2).
- Produces: `google_project_service.apis` (a `for_each` map keyed by API name) — Task 4 and Task 5 resources `depends_on` this so they never race API enablement.

- [ ] **Step 1: Write `terraform/main.tf`**

```hcl
locals {
  required_apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project = var.project_id
  service = each.value

  # Never let `terraform destroy` disable project-wide APIs — this phase's
  # destroy/apply round-trip test (Task 6) should be fast and side-effect
  # free, not silently disable APIs other things in the project may use.
  disable_on_destroy = false
}
```

- [ ] **Step 2: Plan and apply**

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Expected: plan shows 7 `google_project_service.apis` resources to add; apply completes with `Apply complete! Resources: 7 added, 0 changed, 0 destroyed.`

- [ ] **Step 3: Verify against real GCP state**

```bash
gcloud services list --enabled --project=YOUR_PROJECT_ID \
  --filter="name:(run.googleapis.com OR artifactregistry.googleapis.com OR secretmanager.googleapis.com OR monitoring.googleapis.com)"
```

Expected: all four listed as enabled.

- [ ] **Step 4: Commit**

```bash
git add terraform/main.tf
git commit -m "infra: enable required GCP APIs via Terraform"
```

---

### Task 4: Artifact Registry + least-privilege service account

**Files:**
- Create: `terraform/artifact_registry.tf`
- Create: `terraform/iam.tf`

**Interfaces:**
- Consumes: `var.service_name`, `var.region` (Task 2), `google_project_service.apis` (Task 3).
- Produces: `google_artifact_registry_repository.backend`, `google_service_account.cloud_run_runtime` (email consumed by Phase 2's Cloud Run service config and by Task 5's per-secret IAM bindings below).

- [ ] **Step 1: Write `terraform/artifact_registry.tf`**

```hcl
resource "google_artifact_registry_repository" "backend" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for the ${var.service_name} Cloud Run service."

  depends_on = [google_project_service.apis]
}
```

- [ ] **Step 2: Write `terraform/iam.tf`**

```hcl
resource "google_service_account" "cloud_run_runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "${var.service_name} Cloud Run runtime identity"
  description  = "Runtime identity for the Cloud Run service. Least-privilege: read access to this project's own Secret Manager secrets only, granted per-secret in secrets.tf — nothing else."

  depends_on = [google_project_service.apis]
}
```

(The per-secret IAM bindings that grant this service account `secretAccessor` live in Task 5, once the secrets it needs to bind to exist.)

- [ ] **Step 3: Plan and apply**

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Expected: 2 resources added (`google_artifact_registry_repository.backend`, `google_service_account.cloud_run_runtime`).

- [ ] **Step 4: Verify against real GCP state**

```bash
gcloud artifacts repositories describe memegpt-backend \
  --project=YOUR_PROJECT_ID --location=us-central1 --format="value(name,format)"

gcloud iam service-accounts describe memegpt-backend-run@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --format="value(email,disabled)"
```

Expected: repository name/format echoed back (`DOCKER`); service account email echoed back, `disabled: False`.

- [ ] **Step 5: Commit**

```bash
git add terraform/artifact_registry.tf terraform/iam.tf
git commit -m "infra: add Artifact Registry repo and Cloud Run runtime service account"
```

---

### Task 5: Secret Manager containers + per-secret IAM

**Files:**
- Create: `terraform/secrets.tf`
- Modify: `terraform/iam.tf` (add the per-secret IAM binding)

**Interfaces:**
- Consumes: `var.secret_names` (Task 2), `google_service_account.cloud_run_runtime` (Task 4), `google_project_service.apis` (Task 3).
- Produces: `google_secret_manager_secret.backend` (map keyed by secret name) — Phase 2's Cloud Run service config mounts these as env vars by name; `google_secret_manager_secret_iam_member.runtime_secret_access`.

- [ ] **Step 1: Write `terraform/secrets.tf`**

```hcl
resource "google_secret_manager_secret" "backend" {
  for_each = toset(var.secret_names)

  secret_id = each.value
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}
```

- [ ] **Step 2: Append the per-secret IAM binding to `terraform/iam.tf`**

Add below the existing `google_service_account.cloud_run_runtime` resource:

```hcl

resource "google_secret_manager_secret_iam_member" "runtime_secret_access" {
  for_each = google_secret_manager_secret.backend

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_runtime.email}"
}
```

- [ ] **Step 3: Plan and apply**

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Expected: 22 resources added — 11 `google_secret_manager_secret.backend[...]` + 11 `google_secret_manager_secret_iam_member.runtime_secret_access[...]`.

- [ ] **Step 4: Verify against real GCP state**

```bash
gcloud secrets list --project=YOUR_PROJECT_ID --format="value(name)" | sort

gcloud secrets get-iam-policy GROQ_API_KEY --project=YOUR_PROJECT_ID \
  --format="value(bindings.role)"
```

Expected: all 11 secret ids listed (no versions — `gcloud secrets versions list GROQ_API_KEY` should report none); the IAM policy check shows `roles/secretmanager.secretAccessor`.

- [ ] **Step 5: Commit**

```bash
git add terraform/secrets.tf terraform/iam.tf
git commit -m "infra: provision Secret Manager containers and runtime IAM bindings"
```

---

### Task 6: Outputs, README, full destroy/apply round-trip, docs update

**Files:**
- Create: `terraform/outputs.tf`
- Create: `terraform/README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Consumes: every resource from Tasks 3–5.
- Produces: nothing new consumed by later phases beyond what Tasks 3–5 already expose; this task's outputs are for human/CI readability (Phase 3's GitHub Actions will read `artifact_registry_repository` and `cloud_run_runtime_service_account_email` via `terraform output`).

- [ ] **Step 1: Write `terraform/outputs.tf`**

```hcl
output "artifact_registry_repository" {
  description = "Full Artifact Registry repository path for `docker push` / CI image tags."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}"
}

output "cloud_run_runtime_service_account_email" {
  description = "Service account Phase 2's Cloud Run service should run as."
  value       = google_service_account.cloud_run_runtime.email
}

output "secret_ids" {
  description = "Secret Manager secret ids provisioned as empty containers — no values."
  value       = [for s in google_secret_manager_secret.backend : s.secret_id]
}
```

- [ ] **Step 2: Write `terraform/README.md`**

```markdown
# terraform/

Provisions MemeGPT backend's GCP foundation: enabled APIs, Artifact
Registry, a least-privilege Cloud Run runtime service account, and empty
Secret Manager containers. See `../CLOUD_MIGRATION_MASTER.md` for the full
migration plan this is Phase 1 of.

## Bootstrap from zero

1. Install tooling: `brew install terraform google-cloud-sdk`
2. Authenticate: `gcloud auth login && gcloud auth application-default login`
3. Create a GCP project and link billing:
   ```bash
   gcloud projects create YOUR_PROJECT_ID --name="MemeGPT"
   gcloud billing accounts list
   gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
   gcloud config set project YOUR_PROJECT_ID
   gcloud services enable serviceusage.googleapis.com --project=YOUR_PROJECT_ID
   ```
4. Create the versioned GCS state bucket:
   ```bash
   gcloud storage buckets create gs://YOUR_PROJECT_ID-tfstate \
     --project=YOUR_PROJECT_ID --location=us-central1 --uniform-bucket-level-access
   gcloud storage buckets update gs://YOUR_PROJECT_ID-tfstate --versioning
   ```
5. Configure and init:
   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars   # fill in project_id
   cp backend.hcl.example backend.hcl             # fill in bucket name
   terraform init -backend-config=backend.hcl
   ```
6. `terraform apply`.

## Adding a real secret value

Terraform only creates empty Secret Manager containers — it never sets
values (see the repo's `CLAUDE.md` hard invariants). After `apply`:

```bash
echo -n "actual-value" | gcloud secrets versions add GROQ_API_KEY \
  --project=YOUR_PROJECT_ID --data-file=-
```

## What's here vs. later phases

This directory currently covers Phase 1 only: state backend, APIs,
Artifact Registry, IAM, Secret Manager containers. No Cloud Run service
exists yet — that's Phase 2 (`cloud_run.tf`, not yet written).
```

- [ ] **Step 3: Full destroy/apply round-trip verification**

This is Phase 1's actual test, per `CLOUD_MIGRATION_MASTER.md`: "that round-trip is the actual test of infrastructure-as-code."

```bash
cd terraform
terraform destroy
# type "yes" when prompted; confirm it reports resources destroyed, not an error

terraform apply
# type "yes" when prompted
```

Then re-run every verify command from Tasks 3–5 (`gcloud services list`, `gcloud artifacts repositories describe`, `gcloud iam service-accounts describe`, `gcloud secrets list`) and confirm they all report the same state as before the destroy. State plainly in the phase write-up (Task 6 of this task, i.e. the commit message / follow-up note to the user) whether the round-trip passed.

- [ ] **Step 4: Update `CLAUDE.md`**

Add a line to the "Hard invariants" section (after the existing "Blank all real credentials before any local verification run." line):

```markdown
- GCP infrastructure is Terraform-managed (`terraform/`) — never click-ops a
  change in the GCP Console that isn't reflected back into `.tf` files.
  Secret *values* are the one exception: added via `gcloud secrets versions
  add`, never via a `google_secret_manager_secret_version` resource.
```

Also add a `terraform/` entry to the Repository Layout tree near `render.yaml`, one line: `terraform/                   GCP infra as code (Phase 1 of CLOUD_MIGRATION_MASTER.md)`.

- [ ] **Step 5: Update `docs/DECISIONS.md`**

Add a new section at the end, before "Deployment" if that section still describes only Render (leave Render's existing section untouched — it's still accurate until Phase 2/cutover), otherwise append after the most recent dated section:

```markdown
## Cloud migration Phase 1 — Terraform foundation (2026-08-26)

- **Secret Manager holds containers only — Terraform never creates a
  `google_secret_manager_secret_version` resource.** Values are added
  out-of-band via `gcloud secrets versions add`, keeping every credential
  out of Terraform state, matching the hard invariant that predates this
  migration (secrets never in state/`.tf`/git).
- **Per-secret IAM bindings, not a project-wide `secretAccessor` grant** —
  the Cloud Run runtime service account gets `roles/secretmanager.
  secretAccessor` scoped to each of the 11 provisioned secrets
  individually (`google_secret_manager_secret_iam_member` for_each), not
  a blanket project-level role.
- **`disable_on_destroy = false` on every enabled API** — the Phase 1
  destroy/apply round-trip test (the actual verification for this phase)
  needs to be safe to run repeatedly without disabling APIs anything else
  in the project might depend on.
- **GCS backend bucket name lives in a gitignored `backend.hcl`, not
  `versions.tf`** — partial backend configuration, supplied via
  `terraform init -backend-config=`, keeps the project id out of every
  committed file per the "no hardcoded project IDs" requirement.
```

- [ ] **Step 6: Commit**

```bash
git add terraform/outputs.tf terraform/README.md CLAUDE.md docs/DECISIONS.md
git commit -m "infra: Phase 1 outputs, README, and docs (Terraform foundation complete)"
```

---

## Self-Review Notes

- **Spec coverage:** all four Phase 1 numbered items in `CLOUD_MIGRATION_MASTER.md` are covered — (1) `terraform/` root + GCS remote state → Task 2; (2) project services + Artifact Registry + service account + Secret Manager entries → Tasks 3–5; (3) `terraform/README.md` → Task 6; (4) region/service_name/sizing variables, no hardcoded project ids → Task 2. The phase's own "Verify" line (destroy/apply round-trip) → Task 6 Step 3.
- **Placeholder scan:** every step has real, runnable commands or complete `.tf` file contents — no "add appropriate X" language.
- **Type consistency:** `var.secret_names` (Task 2) is the single source of truth consumed identically by `secrets.tf` (Task 5) and referenced by name in `terraform/README.md`'s example (Task 6); `google_service_account.cloud_run_runtime.email` (Task 4) is referenced identically in Task 5's IAM binding and Task 6's output.
