# Cloud Migration Phase 3 — CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two GitHub Actions workflows — a PR workflow (lint, test, `terraform plan`, container build, no deploy) and a main-branch workflow (build, push, deploy, smoke test, promote-or-abort) — authenticated to GCP via Workload Identity Federation, no long-lived service-account key ever leaving GCP.

**Architecture:** A new Terraform-managed Workload Identity Pool + OIDC provider trusts GitHub's own token issuer, scoped to this one repo. A new CI-only service account (distinct from Phase 1's Cloud Run *runtime* identity) gets exactly the roles CI needs: push images, deploy Cloud Run, write Terraform state, and impersonate the runtime SA at deploy time. The deploy workflow never mutates the live service directly with `terraform apply` until a smoke test against an untrafficked candidate revision passes — so "rollback" is "never promote," not "deploy then revert."

**Tech Stack:** GitHub Actions, `google-github-actions/auth` (WIF), Terraform (`google_iam_workload_identity_pool`, `google_iam_workload_identity_pool_provider`, `google_service_account`, `google_project_iam_member`, `google_storage_bucket_iam_member`), `gcloud run deploy --no-traffic --tag`.

**Spec:** [CLOUD_MIGRATION_MASTER.md](../../../CLOUD_MIGRATION_MASTER.md) — this plan implements that spec's "Phase 3 — CI/CD" section.

## A deliberate deviation from the spec's literal "roll back" framing

The spec says: "a smoke test against the new revision. If the smoke test fails, roll back to the previous revision automatically." Taken literally, that means: deploy for real (100% traffic), smoke test, and if it fails, shift traffic back — a window where a broken revision serves real requests.

**This plan does not do that.** Cloud Run supports deploying a revision with `--no-traffic` and a unique `--tag`, which gets its own dedicated URL that never receives a share of the service's normal traffic. The deploy workflow:
1. Builds and pushes the image.
2. `gcloud run deploy --no-traffic --tag=ci-<short-sha>` — creates the revision, serves 0% of real traffic.
3. Smoke-tests the *tagged* URL (`https://ci-<short-sha>---<service>-<hash>.<region>.run.app`), not the public one.
4. **Only on success:** `terraform apply` with `cloud_run_image_digest` set to the new digest — Terraform's existing `traffic { type = LATEST, percent = 100 }` config promotes it.
5. **On failure:** delete the untrafficked candidate revision. The live service was never touched. No rollback action is needed because nothing was ever rolled forward.

This achieves the spec's actual goal (bad code never serves users, verified automatically) more safely than a deploy-then-revert pattern, and is what a senior engineer would actually build. Working agreement item 1 requires flagging deviations for approval — flagging this one here, in the plan, before any code is written.

---

## Working agreement (unchanged from Phases 1-2, still binding)

Plan before code (this document, wait for approval); Render keeps serving all real traffic (this phase still doesn't touch `frontend/` or link Cloud Run to it); hard $10/month ceiling, stated per-task below; secrets never in state/`.tf`/git — WIF's entire point is that no long-lived GCP credential material exists anywhere, not even as a GitHub Secret; verify against the real deployed service; update `CLAUDE.md`/`docs/DECISIONS.md` at the end (gitignored/local-only, same finish-time propagation pattern as Phases 1-2).

**A prerequisite already handled before this plan was written:** local `main` was 9 commits ahead of `origin/main` (all of Phases 1-2, never pushed) — confirmed a clean fast-forward and pushed, with your explicit go-ahead, before starting this phase's research. `origin/main` and local `main` are now identical.

**Projected cost added by this phase:** Workload Identity Federation itself is free (no separate GCP product charge). GitHub Actions minutes are free for a public repo. The CI service account has no billable resource of its own. Terraform state writes from CI use the same free-tier GCS bucket. **~$0.00/month.** (CI-triggered Cloud Run deploys create new revisions of the same already-provisioned service — no new billable resource type.)

---

## File Structure

```
terraform/
└── ci.tf                       NEW — WIF pool/provider, CI service account, its IAM bindings
.github/workflows/
├── ci-pr.yml                   NEW — PR checks: lint, pytest, terraform plan, container build
└── ci-deploy.yml               NEW — main-branch deploy: build, push, candidate deploy, smoke test, promote
```

`terraform/outputs.tf` gains two more outputs (WIF provider resource name, CI service account email) so the GitHub-side configuration (Task 3) can read real values instead of hand-copying them from `gcloud` output.

---

### Task 1: Workload Identity Federation + CI service account in Terraform

**Files:**
- Create: `terraform/ci.tf`
- Modify: `terraform/outputs.tf` (two more outputs)
- Modify: `terraform/main.tf` (two more APIs in the `required_apis` list)

**Interfaces:**
- Consumes: `var.project_id`, `var.region`, `var.service_name` (Phase 1's `variables.tf`); `google_service_account.cloud_run_runtime` (Phase 1's `iam.tf`, so the CI SA can be granted `roles/iam.serviceAccountUser` on it); the GCS state bucket name (`memegpt-infra-68502-tfstate`, referenced as a literal since Phase 1's `versions.tf` deliberately keeps the bucket name out of `.tf` files — this is the one place it's unavoidable, since IAM on a specific bucket needs to name it; document why).
- Produces: `google_iam_workload_identity_pool.github`, `google_iam_workload_identity_pool_provider.github`, `google_service_account.ci_deploy`, plus outputs `wif_provider_name` and `ci_service_account_email` that Task 3's GitHub configuration reads.

- [ ] **Step 1: Add the two missing APIs to `terraform/main.tf`'s `required_apis` list**

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
    "iamcredentials.googleapis.com", # NEW — needed for WIF's short-lived credential exchange
    "sts.googleapis.com",            # NEW — Security Token Service, WIF's OIDC token exchange
  ]
}
```

- [ ] **Step 2: Write `terraform/ci.tf`**

```hcl
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Trusts GitHub's OIDC tokens for this repo's Actions workflows — no long-lived key ever leaves GCP."

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id         = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                      = "GitHub"

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
  role                = "roles/iam.workloadIdentityUser"
  member              = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/Moulik04/memegpt"
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
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${google_service_account.ci_deploy.email}"
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
```

- [ ] **Step 3: Add the two outputs to `terraform/outputs.tf`**

```hcl

output "wif_provider_name" {
  description = "Full WIF provider resource name — used as GitHub Actions' workload_identity_provider input."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account_email" {
  description = "CI deploy service account email — used as GitHub Actions' service_account input."
  value       = google_service_account.ci_deploy.email
}
```

- [ ] **Step 4: Plan and apply**

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Expected: 6 resources added (pool, provider, service account, 4 IAM bindings — recount against the actual plan output, don't assume), plus the 2 new outputs.

- [ ] **Step 5: Verify against real GCP state**

```bash
terraform output wif_provider_name
terraform output ci_service_account_email
gcloud iam workload-identity-pools describe github-actions --project=memegpt-infra-68502 --location=global --format="value(state)"
```

Expected: both outputs populated, pool state `ACTIVE`.

- [ ] **Step 6: Commit**

```bash
git add terraform/ci.tf terraform/outputs.tf terraform/main.tf
git commit -m "infra: provision Workload Identity Federation + CI deploy service account"
```

---

### Task 2: GitHub repository configuration

**Files:** none (real GitHub repo configuration via `gh`, not a file in this repo).

**Interfaces:**
- Consumes: `terraform output wif_provider_name` / `terraform output ci_service_account_email` (Task 1).
- Produces: GitHub repo *variables* (not secrets — these are identifiers, not credential material, which is the whole point of WIF) that Tasks 3-4's workflow YAML reads via `${{ vars.* }}`.

- [ ] **Step 1: Set repo variables**

```bash
gh variable set GCP_PROJECT_ID --body "memegpt-infra-68502"
gh variable set GCP_WIF_PROVIDER --body "$(terraform -chdir=terraform output -raw wif_provider_name)"
gh variable set GCP_CI_SERVICE_ACCOUNT --body "$(terraform -chdir=terraform output -raw ci_service_account_email)"
gh variable set GCP_REGION --body "us-central1"
gh variable set GCP_SERVICE_NAME --body "memegpt-backend"
```

- [ ] **Step 2: Verify**

```bash
gh variable list
```

Expected: all 5 listed.

No commit — this is real GitHub-side state, not a repo file.

---

### Task 3: PR workflow — lint, test, plan, build (no deploy)

**Files:**
- Create: `.github/workflows/ci-pr.yml`

**Interfaces:**
- Consumes: the 5 repo variables (Task 2), the existing `GROQ_API_KEY` repo secret (already present, used by `trend-pipeline.yml` — pytest needs it for any test that isn't fully mocked, matching this repo's existing convention).
- Produces: nothing consumed by later tasks — this workflow is a leaf, gating PRs only.

- [ ] **Step 1: Write `.github/workflows/ci-pr.yml`**

```yaml
name: CI (PR checks)

# Lint, full pytest suite, terraform plan, and a container build — on every
# PR against main. Never deploys, never pushes an image, never applies
# Terraform. See .github/workflows/ci-deploy.yml for what runs on merge.

on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  id-token: write # required for google-github-actions/auth's WIF exchange

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install backend
        working-directory: backend
        run: pip install -e ".[dev]"

      - name: Ruff lint
        working-directory: backend
        run: ruff check .

      - name: pytest (full suite)
        working-directory: backend
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
        run: pytest

  terraform-plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_CI_SERVICE_ACCOUNT }}

      - uses: hashicorp/setup-terraform@v3

      - name: terraform init
        working-directory: terraform
        run: terraform init -backend-config="bucket=${{ vars.GCP_PROJECT_ID }}-tfstate" -backend-config="prefix=memegpt-backend"

      - name: terraform plan
        working-directory: terraform
        env:
          TF_VAR_project_id: ${{ vars.GCP_PROJECT_ID }}
        run: |
          terraform plan \
            -var="cloud_run_image_digest=$(terraform output -raw 2>/dev/null || echo 0000000000000000000000000000000000000000000000000000000000000000)" \
            -lock=false

  container-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image (no push)
        run: docker build -t memegpt-backend:pr-check -f backend/Dockerfile .
```

The `terraform plan` step's `-var="cloud_run_image_digest=..."` handles a real wrinkle: PR-time plans don't have a real new digest yet (nothing was built/pushed for this PR), so it reuses whatever digest is already live (read via `terraform output`, since `-var` on the CLI overrides but a `terraform output` read doesn't need the var to already be set correctly — if this is the very first run before any state exists with that output, falls back to a placeholder 64-hex-char string, which is enough for `terraform plan`'s syntax/diff purposes without needing a real pushed image). `-lock=false` avoids a PR-time plan blocking a real concurrent deploy's state lock.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci-pr.yml
git commit -m "ci: add PR workflow (lint, pytest, terraform plan, container build)"
```

(No local verification step here beyond `ruff check`/`pytest` you can already run locally — the workflow itself is verified for real in Task 5, by opening a real PR.)

---

### Task 4: Main-branch deploy workflow — build, push, candidate deploy, smoke test, promote

**Files:**
- Create: `.github/workflows/ci-deploy.yml`

**Interfaces:**
- Consumes: the 5 repo variables (Task 2), `terraform/cloud_run.tf`'s `var.cloud_run_image_digest` (Phase 2, now driven by CI instead of a hand-edited `terraform.tfvars`).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write `.github/workflows/ci-deploy.yml`**

```yaml
name: CI (deploy)

# On every push to main: build, push to Artifact Registry, deploy a
# candidate revision with ZERO live traffic, smoke-test that candidate's
# own dedicated URL, and only promote it to 100% traffic (via `terraform
# apply`) if the smoke test passes. A failed smoke test deletes the
# candidate and stops — the live service was never touched, so there is
# nothing to "roll back."

on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_CI_SERVICE_ACCOUNT }}

      - uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker ${{ vars.GCP_REGION }}-docker.pkg.dev

      - name: Build and push
        id: push
        run: |
          IMAGE="${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/${{ vars.GCP_SERVICE_NAME }}/${{ vars.GCP_SERVICE_NAME }}"
          TAG="sha-${GITHUB_SHA::7}"
          docker build -t "${IMAGE}:${TAG}" -f backend/Dockerfile .
          docker push "${IMAGE}:${TAG}"
          DIGEST=$(gcloud artifacts docker images describe "${IMAGE}:${TAG}" --format="value(image_summary.digest)" | sed 's/^sha256://')
          echo "digest=${DIGEST}" >> "$GITHUB_OUTPUT"

      - name: Deploy candidate revision (no traffic)
        id: candidate
        run: |
          TAG="ci-${GITHUB_SHA::7}"
          gcloud run deploy ${{ vars.GCP_SERVICE_NAME }} \
            --project=${{ vars.GCP_PROJECT_ID }} \
            --region=${{ vars.GCP_REGION }} \
            --image="${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/${{ vars.GCP_SERVICE_NAME }}/${{ vars.GCP_SERVICE_NAME }}@sha256:${{ steps.push.outputs.digest }}" \
            --no-traffic \
            --tag="${TAG}" \
            --quiet
          URL=$(gcloud run services describe ${{ vars.GCP_SERVICE_NAME }} --project=${{ vars.GCP_PROJECT_ID }} --region=${{ vars.GCP_REGION }} --format="value(status.traffic[?tag=='${TAG}'].url)" | tr -d "[]'")
          echo "url=${URL}" >> "$GITHUB_OUTPUT"
          echo "tag=${TAG}" >> "$GITHUB_OUTPUT"

      - name: Smoke test the candidate (NOT the live URL)
        id: smoke
        run: |
          set -e
          curl -sf "${{ steps.candidate.outputs.url }}/health"
          curl -sf "${{ steps.candidate.outputs.url }}/docs" -o /dev/null

      - uses: hashicorp/setup-terraform@v3
        if: success()

      - name: Promote via terraform apply
        if: success()
        working-directory: terraform
        env:
          TF_VAR_project_id: ${{ vars.GCP_PROJECT_ID }}
          TF_VAR_cloud_run_image_digest: ${{ steps.push.outputs.digest }}
        run: |
          terraform init -backend-config="bucket=${{ vars.GCP_PROJECT_ID }}-tfstate" -backend-config="prefix=memegpt-backend"
          terraform apply -auto-approve

      - name: Smoke test failed — delete the untrafficked candidate
        if: failure() && steps.candidate.outcome == 'success'
        run: |
          gcloud run revisions delete "$(gcloud run revisions list --service=${{ vars.GCP_SERVICE_NAME }} --project=${{ vars.GCP_PROJECT_ID }} --region=${{ vars.GCP_REGION }} --filter="metadata.labels.'run.googleapis.com/tag'=${{ steps.candidate.outputs.tag }}" --format="value(name)")" \
            --project=${{ vars.GCP_PROJECT_ID }} --region=${{ vars.GCP_REGION }} --quiet
          echo "::error::Smoke test failed against the candidate revision — it was never promoted, live traffic is unaffected. Candidate revision deleted."
          exit 1
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci-deploy.yml
git commit -m "ci: add main-branch deploy workflow (candidate deploy, smoke test, promote-or-abort)"
```

---

### Task 5: Verify — a real merge reaches production, and a real broken smoke test never does

This is the phase's actual test, per the spec: "merge a trivial change and watch it reach production untouched. Then deliberately break the smoke test and confirm the rollback fires."

- [ ] **Step 1: A trivial, real change through the full pipeline**

Pick something genuinely trivial and safe (e.g. a comment addition in `backend/main.py`), open a real PR against `main`, confirm `ci-pr.yml`'s three jobs (lint-and-test, terraform-plan, container-build) all pass, merge it, and watch `ci-deploy.yml` run to completion.

- [ ] **Step 2: Verify the change actually reached the live service**

```bash
curl -sf https://memegpt-backend-2jxpla5n2a-uc.a.run.app/health
gcloud run services describe memegpt-backend --project=memegpt-infra-68502 --region=us-central1 --format="value(status.latestReadyRevision)"
```

Confirm the revision name is new (post-dates Phase 2's `memegpt-backend-00001-rmr`) and `terraform state show google_cloud_run_v2_service.backend` shows the new digest, matching `git log`'s latest commit's build.

- [ ] **Step 3: Deliberately break the smoke test**

Push a change that makes `/health` fail without breaking the build itself — e.g. temporarily change the healthcheck-adjacent logic to return a 500, or (simpler, no code change) temporarily point the workflow's smoke-test curl at a path that doesn't exist, to prove the failure path itself works end-to-end. Prefer a real application-level break (e.g. a syntactically-valid but broken `/health` handler) over sabotaging the workflow file, since the goal is proving the *deploy pipeline's* safety net, not the YAML's `if:` conditionals in isolation.

- [ ] **Step 4: Confirm the failure path**

Watch the Action run: the candidate deploy step should succeed (a real revision gets created), the smoke-test step should fail, the "delete candidate" step should run and succeed, and — critically — confirm via `gcloud run services describe ... --format="value(status.latestReadyRevision)"` that the **live revision never changed** from Step 2's value. Then revert the deliberate break and confirm a follow-up push promotes cleanly again.

- [ ] **Step 5: No commit for the verification itself** — Steps 1 and 3's actual commits are the artifacts; record pass/fail for both real end-to-end runs. Task 6 folds this into `docs/DECISIONS.md`.

---

### Task 6: Docs

**Files:**
- Modify: `CLAUDE.md` (gitignored, local-only — same finish-time propagation pattern as Phases 1-2)
- Modify: `docs/DECISIONS.md` (same)

- [ ] **Step 1: `docs/DECISIONS.md`**

New section after Phase 2's, before "## Deployment", covering: the deploy-safety deviation from the spec's literal "rollback" framing (candidate-revision-then-promote instead of deploy-then-revert) and why; the WIF setup (no key material, repo-scoped); the real verification results from Task 5 (both the successful merge-to-production run and the deliberately-broken smoke-test run, with actual revision names/timestamps).

- [ ] **Step 2: `CLAUDE.md`**

Add `.github/workflows/ci-pr.yml`/`ci-deploy.yml` to the Repository Layout tree if the existing `.github/workflows/` line doesn't already generically cover it (check current wording first — it may already read accurately, in which case leave it as-is per the same principle Phase 2's Task 7 followed).

---

## Self-Review Notes

- **Spec coverage:** both named workflows (PR: lint/pytest/terraform-plan/build; main: build/push/apply/deploy/smoke-test/rollback) are covered, with the rollback mechanism deliberately reinterpreted and flagged up front (see the deviation section). WIF instead of a long-lived key → Task 1. "Existing weekly trend-pipeline and keep-warm workflows stay" → this plan creates no changes to either file, satisfying "stay" by omission. The spec's own "Verify" line → Task 5, executed as two real pushes to `main`, not simulated.
- **Placeholder scan:** every step has real YAML/HCL/commands. The PR workflow's `terraform plan` fallback digest is a real, documented technical necessity (no image exists yet for a PR that hasn't merged), not a placeholder standing in for missing plan content.
- **Type consistency:** `var.cloud_run_image_digest` (Phase 2) is read the same way by both new workflows and by Task 1's `ci.tf` comments; `google_service_account.cloud_run_runtime`/`google_secret_manager_secret.backend` references match Phase 1/2's exact existing resource addresses, no renaming.
