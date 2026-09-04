# terraform/

Provisions MemeGPT backend's GCP foundation and the live Cloud Run
service: enabled APIs, Artifact Registry, a least-privilege Cloud Run
runtime service account, empty Secret Manager containers (Phase 1), and
the `google_cloud_run_v2_service` itself, pinned to a specific image
digest (Phase 2, `cloud_run.tf`). See `../docs/INFRASTRUCTURE.md` for
the full migration write-up.

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
6. Create the Artifact Registry repo before anything can be pushed to it.
   `cloud_run.tf`'s `google_cloud_run_v2_service` needs a real image digest
   for even a targeted `apply` to evaluate (`cloud_run_image_digest` has no
   default), so pass a placeholder here — it's only used by resources this
   target excludes:
   ```bash
   terraform apply -target=google_artifact_registry_repository.backend \
     -var="cloud_run_image_digest=placeholder"
   ```
7. Build and push the backend image (needed before the *full* apply, since
   `cloud_run.tf` references a specific image digest via
   `var.cloud_run_image_digest`):
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   docker build -t memegpt-backend:local -f backend/Dockerfile .   # from repo root
   docker tag memegpt-backend:local \
     us-central1-docker.pkg.dev/YOUR_PROJECT_ID/memegpt-backend/memegpt-backend:latest
   docker push \
     us-central1-docker.pkg.dev/YOUR_PROJECT_ID/memegpt-backend/memegpt-backend:latest
   gcloud artifacts docker images describe \
     us-central1-docker.pkg.dev/YOUR_PROJECT_ID/memegpt-backend/memegpt-backend:latest \
     --format="value(image_summary.digest)"
   # copy the digest (without the "sha256:" prefix) into terraform.tfvars as cloud_run_image_digest
   ```
8. `terraform apply` (full — creates the Cloud Run service against the real
   digest now in `terraform.tfvars`).

## Adding a real secret value

Terraform only creates empty Secret Manager containers — it never sets
values. After `apply`:

```bash
echo -n "actual-value" | gcloud secrets versions add GROQ_API_KEY \
  --project=YOUR_PROJECT_ID --data-file=-
```

`google_secret_manager_secret.backend` carries `lifecycle { prevent_destroy
= true }`, so `terraform destroy` (and the destroy/apply round-trip this
phase's own README documents as its standard verification ritual) will
refuse to remove these secrets once any real value has been added.
Removing an entry from `var.secret_names` is therefore a deliberate
two-step action, never an accident: first set `prevent_destroy = false` on
the resource and `apply` that change, then remove the entry from the list
and `apply` again.

## What's here vs. later phases

This directory covers Phase 1 (state backend, APIs, Artifact Registry,
IAM, Secret Manager containers) and Phase 2 (`cloud_run.tf` — the live
Cloud Run service, pinned to a specific image digest via
`var.cloud_run_image_digest`). CI/CD around `terraform plan`/`apply`
(Phase 3) and everything past it are documented in
`../docs/INFRASTRUCTURE.md`, not here.
