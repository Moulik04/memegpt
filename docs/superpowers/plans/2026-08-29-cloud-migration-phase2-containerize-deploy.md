# Cloud Migration Phase 2 — Containerize and Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production Docker image for the backend, push it to the Artifact Registry repo Phase 1 provisioned, deploy it as a Cloud Run service (using Phase 1's service account and Secret Manager containers), and verify the full request flow — including image-upload moderation — against the live Cloud Run URL. Render keeps serving all real traffic; Cloud Run runs in parallel, unlinked from the frontend, purely for verification.

**Architecture:** One new multi-stage `backend/Dockerfile` (replacing today's single-stage, hand-duplicated-dependency-list one) built and smoke-tested locally, pushed to Phase 1's Artifact Registry repo, then deployed via one new `terraform/cloud_run.tf` resource (`google_cloud_run_v2_service`) using Phase 1's runtime service account and mounting `GROQ_API_KEY`/`GEMINI_API_KEY` from Secret Manager as env vars — the only two secrets Render's production deployment actually sets today (`render.yaml`), so this phase reaches exact feature parity with current production, not a superset.

**Tech Stack:** Docker (multi-stage build), Terraform (`google_cloud_run_v2_service`, `google_cloud_run_v2_service_iam_member`), GCP Cloud Run v2, Artifact Registry, Secret Manager.

**Spec:** [CLOUD_MIGRATION_MASTER.md](../../../CLOUD_MIGRATION_MASTER.md) — this plan implements that spec's "Phase 2 — Containerize and deploy" section, plus its "one real architectural problem" note (ChromaDB statelessness), plus a related filesystem-writability problem this planning pass found that the spec didn't name (below).

## A problem the spec didn't name: Cloud Run's filesystem is read-only

Two places in this codebase write to the local container filesystem at runtime:

1. `backend/vector_db/chroma_client.py`'s `_DB_PATH` (`backend/data/chroma/`) — ChromaDB's embedded `PersistentClient`. The spec's own "one real architectural problem" section already covers this: `main.py`'s `_auto_seed_if_empty()` **already exists and already does the right thing** — it prefers `backend/data/template_embeddings.json` (no live Gemini call) and seeds in a background task so `/chat/` works immediately even mid-seed. No backend code change is needed for this half of the problem; Cloud Run just needs a writable place for it to seed *into*.
2. `backend/storage/save_meme()` — when R2 isn't configured (and this phase isn't turning R2 on: Render's production doesn't set it either, so neither does this phase, to stay at parity), every generated meme is written to `backend/static/generated/` and served back from there. **The spec doesn't mention this path at all**, but it has the same problem: Cloud Run's default container filesystem is read-only outside `/tmp`.

Without a fix, every single meme-generating request (`/chat/`, `/lore/`, `/generate/`) would 500 on Cloud Run — this isn't a corner case, it blocks this phase's own verification step entirely.

**Fix, zero backend code changes, zero extra cost:** mount an in-memory `empty_dir` volume (Cloud Run v2's built-in ephemeral-tmpfs-backed volume type) at each path, sized small (64Mi each — the template catalog's vectors are a few MB and `static/generated` only needs to hold a handful of recent PNGs). This is pure Terraform, in Task 5 below.

**What this fix does NOT solve, and is explicitly out of scope for this phase:** an in-memory volume is per-instance. If Cloud Run ever runs more than one instance (it can, once `var.cloud_run_max_instances > 1` and real traffic arrives), a meme generated on instance A won't be visible from instance B, and a cold start wipes whatever was there. That's fine for this phase's own verification (one continuous testing session) and fine for running in parallel with Render pre-cutover (nothing links to Cloud Run's meme URLs yet), but it is a **real blocker for actual cutover** — durable meme storage needs Cloudflare R2 turned on (which `save_meme()` already supports natively — no code change, just real R2 credentials in the already-provisioned `R2_*` Secret Manager containers) before Cloud Run ever serves real traffic. Flagging this explicitly now, to resolve before cutover, not silently discovering it then.

---

## Working agreement (unchanged from Phase 1, still binding)

Same six points as Phase 1's plan: plan before code (this document, wait for approval); the live Render demo must not break (this phase only adds a new, disconnected Cloud Run service — `frontend/` is untouched); hard $10/month ceiling, stated per-task below; secrets never in state/`.tf`/git (real values go in only via `gcloud secrets versions add`, run by you); verify against the real deployed service; update `CLAUDE.md`/`docs/DECISIONS.md` at the end (both gitignored/local-only — Phase 1 already established the pattern of editing them directly in the main checkout at finish time, not through this worktree's commits).

**Projected cost added by this phase:** Cloud Run with `min_instances = 0` (Phase 1's default) bills nothing while idle; this phase's own testing traffic is a handful of requests. Artifact Registry storage for one ~300–400MB image is inside the free tier (0.5GB). **~$0.00–$0.05/month.** (Real per-request cost only starts accruing once traffic is real, i.e. post-cutover — out of scope here.)

---

## File Structure

```
backend/
├── Dockerfile              Rewritten: multi-stage, pyproject.toml-driven (Task 1)
.dockerignore                NEW at repo root — backend/.dockerignore today is dead code,
                              since the Docker build context is the repo root, not backend/
                              (docker-compose.yml's `context: .`) (Task 1)
terraform/
└── cloud_run.tf             NEW — google_cloud_run_v2_service + public-invoker IAM (Task 5)
```

`terraform/outputs.tf` gains one more output (the Cloud Run URL) as part of Task 5, since it's the same file Phase 1 already created.

---

### Task 1: Multi-stage Dockerfile + fix the dead `.dockerignore`

**Files:**
- Modify: `backend/Dockerfile`
- Create: `.dockerignore` (repo root)
- Delete: `backend/.dockerignore` (dead — build context is repo root, so Docker never reads a `.dockerignore` living inside `backend/`; its content moves to the new root one)

**Interfaces:**
- Produces: a Docker image taggable as `${region}-docker.pkg.dev/${project_id}/${service_name}/${service_name}:TAG`, listening on `$PORT` (Cloud Run injects this; the existing `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]` already handles it — keep it unchanged).
- Consumes: `backend/pyproject.toml`'s `dependencies` list as the single source of truth for installed packages — no more hand-duplicated `pip install "fastapi>=...` list.

- [ ] **Step 1: Write the new `backend/Dockerfile`**

```dockerfile
# ---- Builder stage: install dependencies into a venv ----
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

# ---- Runtime stage: slim, no build toolchain ----
FROM python:3.11-slim

WORKDIR /app

# System deps: curl (healthcheck), libfreetype6 + fontconfig (Pillow fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libfreetype6 \
    libfontconfig1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/share/fonts/truetype/Anton-Regular.ttf \
       "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy source code
COPY backend/ .
COPY scripts/ ./scripts

# Runtime dirs + symlink so seed_templates.py resolves /backend → /app
RUN mkdir -p static/generated fonts templates && ln -sf /app /backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/health || exit 1

# PORT is injected by Render and by Cloud Run at runtime; fallback to 8000 for local Docker
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`pip install .` (not `-e .` or `.[dev]`) installs exactly `pyproject.toml`'s `dependencies` list — no dev/test tooling in the production image, no drift between what's declared and what's installed. `build-essential` in the builder stage exists only in case any dependency needs to compile a C extension; it never reaches the runtime stage.

- [ ] **Step 2: Write the new root `.dockerignore`**

```
backend/.venv
backend/__pycache__
backend/**/__pycache__
backend/**/*.pyc
backend/.pytest_cache
backend/.mypy_cache
backend/.ruff_cache
backend/data/chroma
backend/static/generated
backend/.env
.env
frontend/
volumes/
.git/
.claude/
terraform/
docs/
*.md
```

(Same content as the old `backend/.dockerignore`, plus `.env`/`.claude/`/`terraform/`/`docs/`/`*.md` since the build context is now known to be the repo root, where those also exist and have no reason to enter the image.)

- [ ] **Step 3: Delete the dead file**

```bash
git rm backend/.dockerignore
```

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile .dockerignore
git commit -m "infra: multi-stage Dockerfile driven by pyproject.toml, fix dead .dockerignore"
```

(Local build/run verification is Task 2, not this task — keep them separate so this task's diff is reviewable on its own.)

---

### Task 2: Local build and smoke test

**Files:** none (verification only).

**Interfaces:**
- Consumes: `backend/Dockerfile` (Task 1).
- Produces: a locally-tagged image (`memegpt-backend:local`) that Task 3 re-tags and pushes — no need to rebuild.

Docker Desktop isn't currently running on this machine (`docker info` fails to reach the daemon) — if it still isn't by the time this task runs, start it first (`open -a Docker` and wait for it to report ready, or ask the user to start it).

- [ ] **Step 1: Build**

```bash
docker build -t memegpt-backend:local -f backend/Dockerfile .
```

Run from the repo root (build context must be `.`, matching `docker-compose.yml`'s existing convention and the `COPY backend/...`/`COPY scripts/...` paths in the Dockerfile).

- [ ] **Step 2: Run locally with real Groq credentials**

The real `GROQ_API_KEY` needed here is the same one already in this machine's `backend/.env` or Render's dashboard — do not hardcode it into any command that gets logged; export it into a shell variable first and reference the variable.

```bash
docker run --rm -d --name memegpt-backend-local -p 8080:8080 \
  -e PORT=8080 \
  -e LLM_PROVIDER=groq \
  -e GROQ_API_KEY="$GROQ_API_KEY" \
  -e GROQ_MODEL=qwen/qwen3.6-27b \
  memegpt-backend:local
```

- [ ] **Step 3: Wait for health, then hit `/docs`**

```bash
sleep 5
curl -sf http://localhost:8080/health && echo " health OK"
curl -sf http://localhost:8080/docs -o /dev/null -w "%{http_code}\n"
```

Expected: health returns 200, `/docs` returns `200`.

- [ ] **Step 4: One real `/chat/` request**

```bash
curl -sN -X POST http://localhost:8080/chat/ \
  -H "Content-Type: application/json" \
  -H "X-MemeGPT-User: phase2-local-test" \
  -d '{"message": "when the deploy finally works"}'
```

Expected: an SSE stream ending in a `done` event with a `meme_url`, then a `batch_done` event. This is the same `_stream_batch` pipeline documented in `CLAUDE.md`'s Data Flow section — confirms the container can reach Groq, ChromaDB seeding worked (even from a cold local start), and Pillow/font rendering works inside the new multi-stage image.

- [ ] **Step 5: Stop the container**

```bash
docker stop memegpt-backend-local
```

- [ ] **Step 6: No commit** — this task is pure verification, nothing to commit. Record the result (pass/fail, and anything notable about container startup time) for the next task's context.

---

### Task 3: Push the image to Artifact Registry

**Files:** none (infra action only).

**Interfaces:**
- Consumes: the `memegpt-backend:local` image (Task 2) and the Artifact Registry repo URL (Phase 1's `terraform output artifact_registry_repository`, or the known value `us-central1-docker.pkg.dev/memegpt-infra-68502/memegpt-backend`).
- Produces: a pushed image at `us-central1-docker.pkg.dev/memegpt-infra-68502/memegpt-backend/memegpt-backend:phase2-manual`, which Task 5's Terraform resource references by exact tag.

- [ ] **Step 1: Authenticate Docker to Artifact Registry (one-time per machine)**

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

- [ ] **Step 2: Tag and push**

```bash
docker tag memegpt-backend:local \
  us-central1-docker.pkg.dev/memegpt-infra-68502/memegpt-backend/memegpt-backend:phase2-manual

docker push \
  us-central1-docker.pkg.dev/memegpt-infra-68502/memegpt-backend/memegpt-backend:phase2-manual
```

- [ ] **Step 3: Verify**

```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/memegpt-infra-68502/memegpt-backend \
  --format="table(package,version,createTime)"
```

Expected: the `phase2-manual` tag listed.

This tag is deliberately fixed and manual — Phase 3's CI/CD replaces this with git-SHA-based tags built and pushed automatically on every merge. Nothing to commit for this task either.

---

### Task 4: Populate the real GROQ_API_KEY and GEMINI_API_KEY secret values

**Files:** none (this is real-credential handling — run by you, not committed anywhere, never pasted into a command another process logs).

**Interfaces:**
- Consumes: Phase 1's `google_secret_manager_secret.backend["GROQ_API_KEY"]` and `["GEMINI_API_KEY"]` (empty containers, provisioned in Phase 1, still empty).
- Produces: one real secret version each — the only two secrets this phase populates, matching exactly what `render.yaml` sets in production today (nothing else — `DATABASE_URL`/`R2_*`/`SUPABASE_*`/`ANTHROPIC_API_KEY` all stay empty containers, same as current Render production, not a regression).

- [ ] **Step 1: Add the real values (you run this — uses your own key material)**

Use the same `GROQ_API_KEY` and `GEMINI_API_KEY` values already live in Render's dashboard (or your own `backend/.env`, if it's current):

```bash
echo -n "your-real-groq-key" | gcloud secrets versions add GROQ_API_KEY \
  --project=memegpt-infra-68502 --data-file=-

echo -n "your-real-gemini-key" | gcloud secrets versions add GEMINI_API_KEY \
  --project=memegpt-infra-68502 --data-file=-
```

- [ ] **Step 2: Verify (agent-run, doesn't touch the value)**

```bash
gcloud secrets versions list GROQ_API_KEY --project=memegpt-infra-68502 --format="value(name,state)"
gcloud secrets versions list GEMINI_API_KEY --project=memegpt-infra-68502 --format="value(name,state)"
```

Expected: one `ENABLED` version each. Never print the value itself — `versions access` is not run by this step.

No commit — nothing in the repo changes.

---

### Task 5: Cloud Run service in Terraform

**Files:**
- Create: `terraform/cloud_run.tf`
- Modify: `terraform/outputs.tf` (add one output)

**Interfaces:**
- Consumes: `var.service_name`/`var.region`/`var.project_id`/`var.cloud_run_cpu`/`var.cloud_run_memory`/`var.cloud_run_min_instances`/`var.cloud_run_max_instances` (all from Phase 1's `variables.tf`, unconsumed until now), `google_service_account.cloud_run_runtime` (Phase 1's `iam.tf`), `google_secret_manager_secret.backend["GROQ_API_KEY"]`/`["GEMINI_API_KEY"]` (Phase 1's `secrets.tf`, real values as of Task 4), the pushed image (Task 3).
- Produces: `google_cloud_run_v2_service.backend`, a new `cloud_run_url` output that Task 6 curls against.

- [ ] **Step 1: Write `terraform/cloud_run.tf`**

```hcl
resource "google_cloud_run_v2_service" "backend" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  deletion_protection = false

  template {
    # Explicit, non-default runtime identity — Phase 1's whole least-privilege
    # story (per-secret secretAccessor, nothing else) only holds if this is
    # set. Omitting it silently falls back to the project's default compute
    # service account, which already carries roles/editor.
    service_account = google_service_account.cloud_run_runtime.email

    scaling {
      min_instance_count = var.cloud_run_min_instances
      max_instance_count = var.cloud_run_max_instances
    }

    timeout                          = "300s" # covers a full multi-meme Lore batch, not just one meme
    max_instance_request_concurrency = 20

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}/${var.service_name}:phase2-manual"

      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
      }

      env {
        name  = "LLM_PROVIDER"
        value = "groq"
      }
      env {
        name  = "GROQ_MODEL"
        value = "qwen/qwen3.6-27b"
      }
      env {
        name  = "GEMINI_EMBEDDING_MODEL"
        value = "gemini-embedding-2"
      }
      env {
        name  = "CORS_ALLOW_ALL_ORIGINS"
        value = "true"
      }
      env {
        name = "GROQ_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GROQ_API_KEY"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend["GEMINI_API_KEY"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "chroma-data"
        mount_path = "/app/data/chroma"
      }
      volume_mounts {
        name       = "static-generated"
        mount_path = "/app/static/generated"
      }
    }

    # In-memory, per-instance, ephemeral — solves Cloud Run's read-only
    # container filesystem at zero extra cost. NOT durable across instances
    # or cold starts; see CLOUD_MIGRATION_MASTER.md's "problem the spec
    # didn't name" note. Real cross-instance durability is Cloudflare R2
    # (already supported by storage/save_meme(), not turned on this phase).
    volumes {
      name = "chroma-data"
      empty_dir {
        medium     = "MEMORY"
        size_limit = "64Mi"
      }
    }
    volumes {
      name = "static-generated"
      empty_dir {
        medium     = "MEMORY"
        size_limit = "64Mi"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_secret_access]
}

# Public ingress — this phase is pre-cutover verification, curled directly,
# not yet linked from frontend/. Matches Render's current publicly-reachable
# setup. Revisit at actual cutover if auth in front of Cloud Run is wanted.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

- [ ] **Step 2: Add the URL output to `terraform/outputs.tf`**

```hcl

output "cloud_run_url" {
  description = "Live URL of the Cloud Run backend service."
  value       = google_cloud_run_v2_service.backend.uri
}
```

- [ ] **Step 3: Plan and apply**

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Expected: 3 resources added (`google_cloud_run_v2_service.backend`, `google_cloud_run_v2_service_iam_member.public_invoker`), plus the new output.

- [ ] **Step 4: Verify against real GCP state**

```bash
terraform output cloud_run_url
gcloud run services describe memegpt-backend --project=memegpt-infra-68502 --region=us-central1 \
  --format="value(status.url,status.conditions[0].status)"
```

Expected: a `https://memegpt-backend-*.run.app` URL, condition status `True` (service ready).

- [ ] **Step 5: Commit**

```bash
git add terraform/cloud_run.tf terraform/outputs.tf
git commit -m "infra: deploy Cloud Run service (public, unlinked from frontend)"
```

---

### Task 6: Full-flow verification against the live Cloud Run URL

**Files:** none (verification only).

**Interfaces:**
- Consumes: `terraform output cloud_run_url` (Task 5).

This is the phase's actual test, per `CLOUD_MIGRATION_MASTER.md`: "every endpoint exercised against the deployed URL, and the `safe_ingest` path specifically."

- [ ] **Step 1: Health, docs**

```bash
URL=$(terraform -chdir=terraform output -raw cloud_run_url)
curl -sf "$URL/health" && echo " health OK"
curl -sf "$URL/docs" -o /dev/null -w "%{http_code}\n"
```

- [ ] **Step 2: Text chat**

```bash
curl -sN -X POST "$URL/chat/" \
  -H "Content-Type: application/json" \
  -H "X-MemeGPT-User: phase2-cloudrun-test" \
  -d '{"message": "when the terraform apply finally succeeds"}'
```

Expected: SSE stream, `done` event with a real `meme_url` pointing back at `$URL/static/generated/...`, then `batch_done`.

- [ ] **Step 3: Image upload through `safe_ingest`**

Use any real photo on disk (e.g. a screenshot) — this exercises `uploads/safe_ingest.py`'s full pipeline (size/dimension checks, moderation call to Groq, `nlp/vision.describe_image()`), which is the "hard invariant" this step specifically has to re-confirm works in the new environment, not assumed from Task 2's local test alone (different network path, different service account, different runtime).

```bash
curl -sN -X POST "$URL/chat/image/" \
  -H "X-MemeGPT-User: phase2-cloudrun-test" \
  -F "images=@/path/to/a/real/photo.jpg" \
  -F "message=this but as a meme"
```

Expected: same SSE shape as Step 2, real `meme_url`. If it 500s, check `gcloud run services logs read memegpt-backend --project=memegpt-infra-68502 --region=us-central1 --limit=50` for the actual error before assuming it's a moderation rejection — a rejection is a normal `plainReply`-only response, not a 500.

- [ ] **Step 4: Lore multi-meme batch**

```bash
curl -sN -X POST "$URL/lore/" \
  -H "Content-Type: application/json" \
  -H "X-MemeGPT-User: phase2-cloudrun-test" \
  -d '{"message": "friend 1: the deploy is stuck\nfriend 2: did you check the logs\nfriend 1: found it, wrong service account\nfriend 2: classic", "meme_count": 2}'
```

Expected: a `plan` event (`total: 2`), two `done` events, then `batch_done` with `succeeded: 2`.

- [ ] **Step 5: Arc**

```bash
curl -sf "$URL/arc" -H "X-MemeGPT-User: phase2-cloudrun-test" | head -c 500
```

Expected: a valid `ArcStats` JSON body (`has_enough` will be `false` for this fresh identity — that's correct, not a failure).

- [ ] **Step 6: Measure and report cold-start / seeding time**

Per the spec: "Startup time goes up; measure it and report the number." Force a fresh instance and time it:

```bash
gcloud run services update-traffic memegpt-backend --project=memegpt-infra-68502 --region=us-central1 --to-latest
time curl -sf "$URL/health"
```

(If `min_instance_count = 0`, the service will have scaled to zero between testing steps naturally — the first `curl` after an idle period already measures a real cold start. Report the wall-clock number either way.)

- [ ] **Step 7: No commit** — record the pass/fail of every step above and the measured cold-start number; Task 7 folds the number into `docs/DECISIONS.md`.

---

### Task 7: Docs

**Files:**
- Modify: `CLAUDE.md` (gitignored, local-only — edit the worktree's copy; propagate to the main checkout at finish time, same as Phase 1)
- Modify: `docs/DECISIONS.md` (same gitignore situation)

**Interfaces:** none — pure documentation.

- [ ] **Step 1: `CLAUDE.md`**

No new hard invariant needed (Phase 1's "GCP infrastructure is Terraform-managed" line already covers this). Update the Repository Layout's `terraform/` line if `cloud_run.tf` warrants a mention, or leave as-is if the existing one-line summary still reads accurately.

- [ ] **Step 2: `docs/DECISIONS.md`**

Add a new section after Phase 1's, before "## Deployment":

```markdown
## Cloud migration Phase 2 — Containerize and deploy (2026-08-29)

- **A filesystem-writability problem the original migration plan didn't
  name, found during Phase 2 planning:** Cloud Run's container filesystem
  is read-only outside `/tmp`. Two paths need to write at runtime —
  ChromaDB's embedded `PersistentClient` (`backend/data/chroma/`) and
  `storage.save_meme()`'s local-disk fallback (`backend/static/generated/`,
  used whenever R2 isn't configured — which this phase deliberately keeps
  true, to stay at exact Render-production parity). Fixed with two
  in-memory (`empty_dir`, `medium = "MEMORY"`) Cloud Run volumes, zero
  backend code changes, zero extra cost. **Not** a fix for cross-instance
  durability — a meme generated on one instance isn't visible from
  another, and a cold start wipes it. That's fine pre-cutover (nothing
  points at Cloud Run's URLs yet) but is a real blocker for actual cutover:
  Cloudflare R2 needs to be turned on first (already supported by
  `save_meme()`, just needs real credentials in the `R2_*` Secret Manager
  containers Phase 1 already provisioned).
- **ChromaDB's own statelessness problem (the one the spec did name) needed
  no backend code change at all** — `main.py`'s `_auto_seed_if_empty()`
  already preferred the precomputed `template_embeddings.json` over a live
  Gemini call and already ran as a non-blocking background task. Cold-start
  seed time measured at approximately <N>s (fill in from Task 6 Step 6).
- **Docker image rebuilt multi-stage, driven by `pyproject.toml`** instead
  of a hand-duplicated `pip install` list that had already started
  drifting from it.
- **This phase reaches exact Render-production parity, not a superset:**
  only `GROQ_API_KEY`/`GEMINI_API_KEY` got real Secret Manager values —
  every other provisioned secret (`DATABASE_URL`, `R2_*`, `SUPABASE_*`,
  `ANTHROPIC_API_KEY`, `DISCORD_WORKER_SHARED_SECRET`) stays an empty
  container, matching what `render.yaml` does and doesn't set today.
- **Public ingress (`allUsers` + `roles/run.invoker`)**, matching Render's
  current publicly-reachable setup. The service is still fully unlinked
  from `frontend/` — nothing routes real traffic here yet.
```

- [ ] **Step 3: No git commit for this task's own content** — same gitignore situation as Phase 1: these two files are untracked and will be propagated to the main checkout directly at finish time, not through a worktree commit.

---

## Self-Review Notes

- **Spec coverage:** all 5 numbered Phase 2 items in `CLOUD_MIGRATION_MASTER.md` are covered — (1) multi-stage Dockerfile, Ollama-free → Task 1 (the existing Dockerfile was already Ollama-free; multi-stage + pyproject-driven is the actual gap); (2) build/run/verify locally before pushing → Task 2; (3) Cloud Run service in Terraform with concurrency/CPU/memory/timeout/min-max/secrets → Task 5; (4) deploy + full-flow verification → Task 6; (5) don't cut over, both run in parallel → Task 5's public-but-unlinked ingress, no `frontend/` changes anywhere in this plan. The spec's own architectural note (ChromaDB statelessness) → addressed by existing code, verified in Task 6 Step 6. Plus one problem the spec didn't name (filesystem writability) → Task 5's volume mounts, documented in Task 7.
- **Placeholder scan:** every step has real commands or complete file contents; Task 6 Step 6's "<N>s" is explicitly a fill-in-after-measuring placeholder in the *documentation template*, not a step to execute — flagged inline as such, not a plan defect.
- **Type consistency:** `google_service_account.cloud_run_runtime` (Phase 1's `iam.tf`) and `google_secret_manager_secret.backend["GROQ_API_KEY"]`/`["GEMINI_API_KEY"]` (Phase 1's `secrets.tf`) are referenced in Task 5 with the exact same resource addresses Phase 1 already established — no renaming, no new resource inventing a different name for the same thing.
