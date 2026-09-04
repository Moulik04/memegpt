# terraform/gke/

Provisions a single GKE Autopilot cluster used for Phase 5's one-shot
Kubernetes verification (`CLOUD_MIGRATION_MASTER.md`, Phase 5). Fully
separate Terraform state from the main `terraform/` stack — its
`destroy` can never affect the live Cloud Run backend.

## Bootstrap

```bash
cd terraform/gke
cp backend.hcl.example backend.hcl   # fill in the real tfstate bucket name
terraform init -backend-config=backend.hcl
terraform apply -var="project_id=YOUR_PROJECT_ID"
```

## Teardown

```bash
terraform destroy -var="project_id=YOUR_PROJECT_ID"
```

`deletion_protection = false` is set deliberately in `main.tf` — this
cluster is meant to be destroyed on demand, unlike the main stack's
Cloud Run service.

## What's here

Just the cluster (`main.tf`) and the two APIs/outputs it needs. The k8s
manifests deployed onto it live in `../../k8s/` at the repo root, applied
directly via `kubectl`, not through this Terraform module — see
`docs/superpowers/plans/2026-09-04-cloud-migration-phase5-kubernetes.md`
Task 3 for the full spin-up/verify/teardown sequence.
