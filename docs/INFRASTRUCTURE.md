# Infrastructure

MemeGPT's backend has been fully migrated to GCP — provisioned entirely
with Terraform, with real CI/CD and real observability — and verified
live under real traffic (`CLOUD_MIGRATION_MASTER.md`, Phases 1-5). The
live public app currently still serves from Render; cutover (pointing
the frontend's `BACKEND_URL` at Cloud Run) is a deliberate, reversible
DNS/env change intentionally held until public launch, not something
left undone by accident — the working agreement that drove this
migration was explicit that Render keeps serving until Cloud Run is
proven under real traffic, which every phase below did. Full
incident-level narrative lives in `docs/DECISIONS.md` (local-only); this
is the public-facing summary with the real, measured numbers.

## Architecture

```
GitHub push to main
      │
      ▼
GitHub Actions (Workload Identity Federation — no key material, ever)
      │
      ├──► lint + full pytest suite (277 tests) + terraform plan + container build   [ci-pr.yml, PRs only]
      │
      └──► build → push to Artifact Registry
                  │
                  ▼
            terraform apply (Terraform-managed, GCS remote state)
                  │
                  ▼
            deploy candidate revision, --no-traffic, tagged URL
                  │
                  ▼
            smoke test against the tagged URL
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
   pass: promote        fail: never promoted,
   (terraform apply      live traffic untouched,
   shifts traffic)        tag removed immediately
                  │
                  ▼
        Cloud Run (scales to zero, min-instances 0)
                  │
    ┌─────────────┼─────────────────────┐
    ▼             ▼                     ▼
Supabase (PG)  Cloudflare R2      Secret Manager
                                        │
                                        ▼
                          OpenTelemetry → Grafana Cloud
                          (metrics + structured logs,
                           1 dashboard, 3 SLO alerts)
```

Supabase Postgres, Cloudflare R2, Groq, and Gemini stay exactly where
they were — migrating those buys nothing and costs real money (Cloud SQL
alone would blow the project's $10/month ceiling). What moved is the
compute layer (Render → Cloud Run) and everything around it: IaC, CI/CD,
observability, and (separately, on demand) a Kubernetes tier.

## Before / after — measured, not estimated

| | Render (before) | Cloud Run (after) |
|---|---|---|
| Cold start | ~30s (15-min idle timeout, real number from `docs/DECISIONS.md`'s deployment notes) | **~8.9s**, instance start to serving-ready (real Cloud Run boot logs, Phase 2) |
| Deploy mechanism | git push, Render's own build pipeline, no IaC | Terraform-managed, GitHub Actions, Workload Identity Federation |
| Deploy time (push → live, verified) | not separately measured — Render's own dashboard, no instrumented pipeline | **~2m37s-3m41s** end to end (real `ci-deploy.yml` run durations: build, push, `terraform apply`, deploy, smoke test, promote) |
| Observability | uptime pings only (`keep-warm.yml`) | Real metrics + structured logs (OTel → Grafana Cloud), 1 dashboard, 3 SLO alerts |
| IaC | none | Terraform, GCS remote state, `terraform destroy && terraform apply` round-trip verified from clean |
| Monthly cost at current traffic | $0 (free tier) | **~$0 steady state** (scales to zero, `min_instances=0`; Secret Manager, Grafana Cloud free tier, Artifact Registry storage all comfortably inside their free tiers) |

The honest framing: this migration didn't reduce cost — both platforms
are effectively free at this project's real traffic volume. What it
bought is real infrastructure-as-code, real CI/CD with an untrafficked
candidate + smoke-test-gated promotion (never a "deploy and hope"), real
push-based observability that survives a scale-to-zero compute model, and
(Phase 5, below) real, verified Kubernetes experience — not cost savings.

**Real observed request latency** (a handful of manually-sent requests
against the live service, not a statistically meaningful production p95
— this project doesn't have production traffic volume yet): `/health`
returns in ~150ms warm; a real end-to-end meme generation (LLM
intent-parse → RAG template pick → Pillow composition) ranges roughly
1.5s-12.4s per request, with the occasional slower sample driven by Groq
response-time variance, not this app's own code. That 12.4s outlier
still lands comfortably under the 20-second SLO threshold below — real
corroboration for where that number was set, not just a guess.

## The ChromaDB statelessness problem

Cloud Run instances are ephemeral and ChromaDB's embedded
`PersistentClient` wants to write to local disk — a real architectural
mismatch, not a config detail. Solved with what already existed:
`backend/data/template_embeddings.json` is a precomputed embeddings file
(from `precompute_template_embeddings.py`), seeded into Chroma's
instance-local storage on cold start. No managed vector DB, no persistent
disk, no added cost. Verified for real: cold start to serving-ready in
~8.9s, background seed complete ~0.6s after that. One real gap the
deployment surfaced (not introduced by it): the precomputed file had
drifted 4 templates behind the live catalog by the time this was
verified — 121 of 125 templates seeded from the file, the remaining 4 via
a live Gemini embedding call, which makes cold-start seeding depend on
Gemini quota in exactly the scenario this design was meant to avoid. This
is a standing hard invariant now (`CLAUDE.md`): re-run
`precompute_template_embeddings.py` whenever the template set changes.

## Cloud Run vs. GKE — the real cost decision

`CLOUD_MIGRATION_MASTER.md` ruled out an always-on Kubernetes tier up
front: a managed control plane (EKS-style) runs ~$73/month before a
single node, which isn't sustainable on this project's $10/month ceiling
and proves nothing extra to anyone reading the code. Cloud Run was
chosen as the actually-live service for exactly that reason.

Kubernetes experience was proven honestly instead: Phase 5 stood up a
real GKE Autopilot cluster, deployed the same production image to it,
verified it against a real public LoadBalancer IP with real HTTP
requests, then tore it down — same session. Real numbers from that run:

- Cluster creation: **9m30s** (real, from the Terraform apply log)
- Cluster teardown: **4m4s**
- Real public-IP exposure window: **~1-3 minutes** (LoadBalancer IP live
  → deleted, minimized deliberately — see `docs/DECISIONS.md`'s Phase 5
  section for the exact sequencing)
- Real session cost: **a few cents, well under $0.10 total** — GKE
  Autopilot's management fee ($0.10/hour, published rate) over the
  cluster's real ~19-minute lifetime, plus a negligible fraction of a
  cent each for the single pod's compute and the LoadBalancer forwarding
  rule's brief existence
- **What running it continuously would cost: ~$73/month** (the
  management fee alone, $0.10/hour × 730 hours) — independently landing
  on the same order of magnitude the master doc cited for EKS before this
  migration even started, which is real corroboration that spin-up/
  verify/destroy was the right call, not just the cheap one.

Real k8s manifests (`k8s/`: Deployment, Service, HPA, ConfigMap, Secret)
and the isolated Terraform module (`terraform/gke/`) both stay in the
repo as working artifacts — a real, reproducible verification, not a
one-off screenshot.

## SLOs — and why these thresholds

Three alerts, defined in Grafana Cloud (`observability/alert-*.json`),
each with an explicit rationale rather than a round number:

1. **p95 meme generation duration < 20s.** Set from this app's real
   generation path (LLM call + RAG + Pillow composition), with headroom
   for Groq's own response-time variance — corroborated by this write-up's
   own 12.4s real sample landing well inside it.
2. **5xx error rate < 2%**, evaluated over a 5-minute rolling window —
   standard availability bar for a service this size, tight enough to
   catch a real regression, loose enough not to page on noise.
3. **Hard-fallback rate < 5%**, evaluated over a 15-minute window (longer
   than the other two — this app's real traffic volume is low enough
   that a 5-minute window would be noisy for a ratio metric). This is
   this app's own real degraded-service signal: a 200 OK with the
   hardcoded fallback meme means both the primary and secondary LLM
   attempts already failed silently to the user.

## One real incident, found and fixed during this migration

**What happened:** Phase 4's real failure-injection test (deliberately
breaking a Cloud Run revision's `GROQ_API_KEY` to prove the observability
pipeline works end to end) used a manual `gcloud run deploy` outside
Terraform. Live traffic was never affected — confirmed throughout via the
service's real traffic-split JSON — but the deploy left the service's
stored *template* (the base Terraform reads for its next change) holding
the broken key as a plain literal, with traffic manually pinned to a
specific revision instead of tracking `LATEST`.

**How it was diagnosed:** caught while gathering real values for Phase
5's Kubernetes manifests — a routine `gcloud run services describe`
showed `GROQ_API_KEY=invalid-test-key` in the live service's env, not
just the test revision's. A `terraform plan` against the main stack's
already-correct declared config confirmed the exact scope: exactly one
resource (`google_cloud_run_v2_service.backend`) would change, restoring
all four secret-backed env vars to proper `secret_key_ref`s and traffic
tracking back to `LATEST` — real, targeted evidence before touching
anything, not a guess.

**The fix:** one `terraform apply`. Cloud Run creates a revision and
reassigns traffic atomically, so there was no window where live traffic
could have reached the broken revision. Verified after: a fresh revision
at 100% traffic, `/health` returning `200`, and a real chat request
returning a genuine LLM-picked template — not the hard-fallback.

**The standing lesson**, now recorded as a real operational fact rather
than a one-off note: any manual `gcloud run deploy` against a
Terraform-managed service is real drift the moment it lands, because
Cloud Run's revision model means even a `--no-traffic` tagged test deploy
alters the service's *stored template*, not just the tested revision. A
manual verification deploy should be followed by a `terraform plan`
before trusting the service's declared state again — checking that live
traffic is untouched isn't sufficient on its own.
