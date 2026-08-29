# CLOUD_MIGRATION_MASTER.md

Move MemeGPT's backend off Render onto GCP, provisioned entirely with Terraform, with real CI/CD and real observability. Hand this to Claude Code in the memegpt directory.

**Why this project:** MemeGPT has shipped product features across eight growth phases, but has no real cloud/infrastructure story — everything runs on Render's managed platform with no IaC, no CI/CD beyond a couple of scheduled workflows, and no observability beyond uptime pings. This project closes that gap directly: it converts "no hands-on cloud platform experience" into "operates a live production service on GCP with Terraform-managed infrastructure, real CI/CD, and real observability."

**Why it's safe to run alongside the frontend rebuild:** the backend is a separate deployable. This work touches `backend/`, `terraform/`, and `.github/workflows/`. It does not touch `frontend/` except for one environment variable at cutover. The two efforts are orthogonal.

---

## Working agreement

1. Plan before code, every phase. Wait for approval.
2. **The live demo must not break.** Render stays running and serving until Cloud Run is verified under real traffic. Cutover is a DNS/env change, reversible in minutes.
3. **Hard cost ceiling: $10/month steady state.** If a design decision would exceed it, stop and say so rather than proceeding. State projected monthly cost in every plan.
4. Secrets never enter Terraform state, `.tf` files, or git. Secret Manager only.
5. Verify against the real deployed service, not `terraform plan` output.
6. Update `CLAUDE.md` invariants and `docs/DECISIONS.md` narrative at the end of each phase.

---

## Target architecture

```
GitHub push to main
      │
      ▼
GitHub Actions ──► build container ──► Artifact Registry
      │                                      │
      │                                      ▼
      └──────────► terraform apply ──► Cloud Run service
                                             │
                        ┌────────────────────┼────────────────────┐
                        ▼                    ▼                    ▼
                  Supabase (PG)       Cloudflare R2        Secret Manager
                                             │
                                             ▼
                              Prometheus metrics ──► Grafana Cloud
```

**Stays as-is:** Supabase Postgres, Cloudflare R2, Groq, Gemini. Migrating those buys nothing and costs money — Cloud SQL alone would blow the budget. The claim being made is "provisions and operates cloud infrastructure with IaC," and Cloud Run + Artifact Registry + Secret Manager + monitoring makes that claim honestly.

**Why Cloud Run and not EKS/GKE:** EKS charges ~$73/month for the control plane before a single node. That is not sustainable on a job-hunt budget, and paying it proves nothing a recruiter can see. Cloud Run scales to zero, has a genuine free tier, and is real containerized production infrastructure. Kubernetes gets addressed separately in Phase 5.

### The one real architectural problem

ChromaDB is stateful and Cloud Run instances are ephemeral. Solve it with what already exists: `backend/data/template_embeddings.json` is committed and `precompute_template_embeddings.py` generates it. Seed Chroma from that file into instance-local storage on startup — no managed vector DB, no persistent disk, no cost. Startup time goes up; measure it and report the number.

If seeding proves too slow for cold starts, the fallback is a `min-instances = 1` setting, which has a real monthly cost. Measure before reaching for it.

---

## Phase 1 — Terraform foundation

1. `terraform/` at repo root. Remote state in a GCS bucket (versioned, with state locking) — not local, not committed.
2. Provision: project services (Cloud Run, Artifact Registry, Secret Manager, Monitoring), an Artifact Registry repo, a service account with least-privilege roles, and Secret Manager entries for every value currently in `backend/.env`.
3. `terraform/README.md` documenting bootstrap from zero: what a fresh clone needs to run to stand the whole thing up.
4. Variables for region, service name, and resource sizing. No hardcoded project IDs.

**Verify:** `terraform destroy` then `terraform apply` from clean, and everything comes back. That round-trip is the actual test of infrastructure-as-code — say plainly whether it passed.

---

## Phase 2 — Containerize and deploy

1. Multi-stage `Dockerfile` for `backend/`. The existing `docker-compose.yml` is a starting point but is built for the local Ollama stack — production is Groq-only, no Ollama layer.
2. Build locally, run locally, hit `/docs` and one real `/chat/` request before pushing anything.
3. Cloud Run service in Terraform: concurrency, CPU, memory, timeout, min/max instances, secrets mounted from Secret Manager as env vars.
4. Deploy. Run the full flow against the Cloud Run URL: text chat, image upload through `safe_ingest`, a Lore multi-meme batch, and an Arc call.
5. **Do not cut over yet.** Both services run in parallel.

**Verify:** every endpoint exercised against the deployed URL, and the `safe_ingest` path specifically — moderation failing closed is a hard invariant and it must be re-verified in the new environment, not assumed.

---

## Phase 3 — CI/CD

GitHub Actions, two workflows:

- **PR:** lint, `pytest` (the full 232-test suite), `terraform plan`, container build. No deploy.
- **main:** build, push to Artifact Registry, `terraform apply`, deploy to Cloud Run, then a smoke test against the new revision. If the smoke test fails, roll back to the previous revision automatically.

Use Workload Identity Federation for GCP auth, not a long-lived service-account JSON key in GitHub secrets. This is the current best practice and it's a detail an interviewer will notice.

The existing weekly trend-pipeline and keep-warm workflows stay; the keep-warm ping may become unnecessary once Cloud Run cold-start numbers are measured.

**Verify:** merge a trivial change and watch it reach production untouched. Then deliberately break the smoke test and confirm the rollback fires.

---

## Phase 4 — Observability

This is the phase that separates the project from a tutorial.

1. Instrument the FastAPI app with `prometheus-fastapi-instrumentator` plus custom metrics that reflect what this system actually does:
   - `meme_generation_duration_seconds` (histogram, labeled by surface)
   - `template_selection_total` (counter, by template_id)
   - `intent_parse_failures_total` and hard-fallback hits
   - `circuit_breaker_state` (the existing Groq/Gemini breakers)
   - `moderation_rejections_total`
   - `cold_start_seconds`
2. Ship to Grafana Cloud's free tier.
3. Build one dashboard that answers real operational questions: p50/p95/p99 latency by surface, error rate, cold-start frequency and duration, LLM provider failure rate, and the template distribution.
4. Define two or three **SLOs** with alerts — e.g. p95 meme generation under 20s, error rate under 2%. An SLO with a stated rationale is a much stronger signal than a wall of graphs.
5. Structured JSON logging with a request/conversation id threaded through, so a single meme generation can be traced end to end.

**Verify:** trigger a real failure (revoke the Groq key briefly on a test revision) and confirm the dashboard and alert both show it.

---

## Phase 5 — The Kubernetes tier

The JDs name Kubernetes specifically, and Cloud Run doesn't give it. Address it honestly and cheaply.

1. Write real k8s manifests for the backend: Deployment, Service, HPA, ConfigMap, Secret, health probes, resource requests and limits.
2. Add a Terraform module for a GKE Autopilot cluster, **kept separate from the main stack and destroyed by default**.
3. Spin it up, deploy, verify it serves real traffic, capture the evidence — `kubectl` output, dashboard screenshots, a short recorded walkthrough — then `terraform destroy`.
4. Document the cost of running it continuously and why it isn't.

This is not a trick. Standing up a cluster, deploying to it, verifying it, and tearing it down *is* Kubernetes experience, and being explicit about the cost tradeoff reads as engineering judgment rather than a gap.

---

## Phase 6 — The write-up

The work only counts if a hiring manager can see it in ninety seconds.

`docs/INFRASTRUCTURE.md`, plus a section in the README:

- Architecture diagram
- **Before/after migration numbers, measured not estimated:** cold start on Render (~30s after 15min sleep) vs Cloud Run, p95 latency, monthly cost, deploy time.
- The ChromaDB statelessness problem and how it was solved from the existing precomputed embeddings
- The Cloud Run vs GKE cost decision, with the actual numbers
- The SLOs and why those thresholds
- One incident or failure found during migration and how it was diagnosed — with the dashboard screenshot

The measured-numbers section is the whole point. "Migrated to GCP" is a claim anyone can make; "cold start went from 31s to 4.2s, cost from $7 to $0.80, and here's the dashboard that shows it" is not.

---

## Order and scope

1 → 2 → 3 → 4 → 6, with 5 slotted after 4. Phases 1–3 are the foundation and are worth roughly a week of evenings. Phase 4 is the differentiator. Phase 6 is not optional — an undocumented migration doesn't close the gap it was built to close.

**Out of scope:** migrating Postgres or R2, multi-region, service mesh, autoscaling tuning beyond defaults. Every one costs money or time and none of them appear in the JD gaps.
