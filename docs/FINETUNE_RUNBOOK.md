# Fine-tuning MemeGPT — Colab Runbook

Growth master-prompt Phase F. Everything up to the actual GPU training run
is automated/verified locally; the training run itself is a manual step the
project owner runs on their own Colab account — that boundary is
intentional (see "Why the hard stop" at the bottom), not a gap.

## 1. Get the dataset

Download the Imgflip 100k meme dataset from Kaggle (free, no special access
needed): search Kaggle for **"imgflip meme generator dataset"**, or go
directly to
[kaggle.com/datasets/dylanrayn/imgflip-meme-generator-100k](https://www.kaggle.com/datasets/dylanrayn/imgflip-meme-generator-100k).
Download the CSV — it has (at least) three columns: a template name column
(`template_name`/`meme_name`/`name`) and two caption columns
(`top_text`/`top`, `bottom_text`/`bottom`). Both scripts below normalize
column-name casing automatically, so minor naming variants are fine.

There's no need to inspect the file by hand first — `scripts/sample_data/imgflip_sample.csv`
(19 hand-written rows, same column shape) already exercises the exact same
code path and is checked into the repo for exactly this reason. If you want
to sanity-check the pipeline before pointing it at the real 100k-row file,
run the commands below against that sample file first.

## 2. Prepare the ChatML training file (local, no GPU, no credentials)

```bash
cd /path/to/memegpt
python3 scripts/prepare_finetune_dataset.py \
    --csv ~/Downloads/imgflip_data.csv \
    --out scripts/memegpt_train.jsonl \
    --limit 20000   # optional — start smaller on a free Colab T4
```

This is pure-stdlib Python (csv/json/re), no backend imports, nothing to
install. Verified against the sample fixture as part of this phase: 19/19
rows converted cleanly into well-formed ChatML records —
`{"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role":
"assistant", "content": "<JSON template_id/texts/reasoning>"}]}`, matching
`nlp/intent_router.py`'s own response contract exactly (the `assistant`
message is literally the same JSON shape `parse_intent()` expects to parse
back out of the LLM at inference time).

*(Optional, not required for training)*: `scripts/ingest_imgflip_dataset.py`
separately loads the same CSV into the few-shot examples store (ChromaDB +
Postgres) for RAG retrieval — a different purpose from the ChatML file
above. It had a real bug (calling an `async` function without `await`,
silently ingesting zero rows) that was found and fixed in this phase;
verified end-to-end against the sample fixture with all real credentials
explicitly blanked. Only run this against your real `DATABASE_URL`/Chroma
store if you actually want the 100k dataset feeding live RAG retrieval —
that's a separate decision from fine-tuning and out of scope for this
runbook.

## 3. Upload to Colab

Open a new Colab notebook, **Runtime → Change runtime type → T4 GPU** (the
free tier), then upload `scripts/memegpt_train.jsonl` via the Colab files
panel (or Google Drive).

## 4. Install dependencies (Colab cell 1)

```python
!pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
!pip install --no-deps "xformers<0.0.27" "trl<0.9.0" peft accelerate bitsandbytes
```

## 5. Run training (Colab cell 2)

Upload `scripts/finetune_unsloth.py` alongside the JSONL (or paste its
contents into a cell) and run:

```python
!python3 finetune_unsloth.py \
    --data memegpt_train.jsonl \
    --out  memegpt_lora \
    --epochs 2
```

The script's defaults are already sized for a free T4 and are what this
runbook recommends starting with — no need to override them for a first
run:

| Flag | Default | Notes |
|---|---|---|
| `--model` | `unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit` | 4-bit quantized base |
| `--rank` | 16 | LoRA rank — bump to 32 only on an A100 |
| `--batch` | 4 | Per-device batch size — drop to 2 if a T4 OOMs |
| `--epochs` | 2 | Budget-realistic for a free Colab session |
| `--seq-len` | 512 | |
| `--lr` | 2e-4 | |

The script auto-detects Bridges2 (`SLURM_JOB_ID` env var) and bumps
batch/rank there instead — no action needed either way, it picks the right
config for wherever it's actually running.

## 6. Expected artifacts

When training finishes, the script prints exactly what it produced:

- A LoRA adapter directory: `memegpt_lora/` (adapter weights + tokenizer).
- A GGUF export: `memegpt_lora_gguf/<some-name>.gguf` (Q4_K_M quantized,
  ready for Ollama). The exact filename comes from Unsloth's export step and
  varies by base model — the script globs for whatever `.gguf` file landed
  there and prints its real name at the end.

## 7. Load the result locally via Ollama

```bash
# Download the .gguf file from Colab, rename it, place at repo root:
mv ~/Downloads/<whatever-unsloth-named-it>.gguf memegpt.gguf
mv memegpt.gguf /path/to/memegpt/memegpt.gguf   # repo root, not scripts/

cd /path/to/memegpt
ollama create memegpt -f scripts/Modelfile
```

`scripts/Modelfile`'s `FROM ./memegpt.gguf` line and this rename step were
reconciled as part of this phase — previously the Modelfile pointed at a
subdirectory/filename combination (`./memegpt_lora_gguf/model-q4_k_m.gguf`)
that didn't match what the training script actually told you to do with the
file ("copy `<gguf_file.name>` to this repo root," not into a subdirectory).
Standardizing on one fixed renamed filename removes that ambiguity for good.

Then, to actually route local dev traffic to it:

```bash
# backend/config.py
ollama_model = "memegpt"   # was "llama3.1:8b"
```

Restart `uvicorn`. This only affects local dev (`LLM_PROVIDER=ollama`) —
production runs `LLM_PROVIDER=groq` and is untouched by any of this.

## 8. Evaluate before trusting it (don't skip this)

Before treating the fine-tuned model's captions as better than what's
already in production, run the pairwise judge added in this same phase:

```bash
cd backend && source .venv/bin/activate
python -m scripts.eval_caption_quality
```

This compares a stored baseline (real 👍-rated captions from
`few_shot_examples`) against a freshly generated candidate for the same
prompt, using Groq as a position-swapped double-blind judge to cancel
ordering bias. As shipped in this phase, "candidate" means today's live
`parse_intent()` pipeline — pointed here so the harness itself is verified
against a real baseline immediately, without waiting on a trained model to
exist. To evaluate the fine-tuned model specifically once you have one
running locally in Ollama, temporarily point local dev at it
(`LLM_PROVIDER=ollama`, `ollama_model = "memegpt"`, per step 7) and rerun
the same script — it calls `parse_intent()`, which already dispatches
through whichever provider `config.py` is currently set to, so no code
change is needed to redirect it.

## 9. Production swap — honestly, not yet a real option

There is currently no free, always-on GPU hosting path for a small
fine-tuned model in production. This is the same constraint that's already
why production runs Groq instead of local Ollama today — Render's free tier
is CPU-only, and CPU inference for an 8B model is far too slow for a
request-time chat feature. Two honest options, neither implemented here:

- **Offline-eval-only** (what this phase ships): run the fine-tuned model
  locally, compare it against production via `eval_caption_quality.py`, and
  use the results to decide whether the underlying prompt/`USE_WHEN`
  catalog should change — without ever routing real user traffic to the
  fine-tuned weights themselves.
- **Small-model self-hosting**, if a genuinely free serving path turns up
  later (e.g. a sufficiently generous free GPU inference tier) — not
  something to build against speculatively; revisit if the landscape
  changes.

## Why the hard stop

Per the master prompt's own services-needed list: *"Phase F: I run the
Colab training myself — you stop at the handoff."* Everything above the
"Run training" cell was verified end-to-end locally as part of this phase
(the ChatML conversion, the (fixed) few-shot ingestion, the Modelfile
handoff path, the eval harness); the training run itself needs a real GPU
session the project owner runs by hand.
