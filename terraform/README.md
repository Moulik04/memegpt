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

`google_secret_manager_secret.backend` carries `lifecycle { prevent_destroy
= true }`, so `terraform destroy` (and the destroy/apply round-trip this
phase's own README documents as its standard verification ritual) will
refuse to remove these secrets once any real value has been added.
Removing an entry from `var.secret_names` is therefore a deliberate
two-step action, never an accident: first set `prevent_destroy = false` on
the resource and `apply` that change, then remove the entry from the list
and `apply` again.

## What's here vs. later phases

This directory currently covers Phase 1 only: state backend, APIs,
Artifact Registry, IAM, Secret Manager containers. No Cloud Run service
exists yet — that's Phase 2 (`cloud_run.tf`, not yet written).
