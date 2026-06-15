"""
Fine-tune Llama-3.1-8B-Instruct on the MemeGPT dataset using Unsloth + LoRA.

Works on: free Colab T4 (16GB VRAM), Bridges2 V100/A100, any CUDA GPU ≥ 12GB.

Setup (run ONCE in Colab or on cluster):
    pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
    pip install --no-deps "xformers<0.0.27" "trl<0.9.0" peft accelerate bitsandbytes

Usage:
    python3 scripts/finetune_unsloth.py \\
        --data scripts/memegpt_train.jsonl \\
        --out  scripts/memegpt_lora \\
        --epochs 2

After training, load into Ollama:
    ollama create memegpt -f scripts/Modelfile
    # Update config.py: ollama_model = "memegpt"

Colab tips:
  - Runtime → Change runtime type → T4 GPU
  - Upload memegpt_train.jsonl to Colab files panel
  - Run this script, then download the .gguf output
"""

from __future__ import annotations

import argparse
import os

# ── Parse args ───────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--data",    default="scripts/memegpt_train.jsonl")
parser.add_argument("--out",     default="scripts/memegpt_lora")
parser.add_argument("--model",   default="unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit")
parser.add_argument("--epochs",  type=int,   default=2)
parser.add_argument("--batch",   type=int,   default=4,    help="Per-device batch size (2 for T4, 4+ for A100)")
parser.add_argument("--rank",    type=int,   default=16,   help="LoRA rank (8 for T4, 32 for A100)")
parser.add_argument("--seq-len", type=int,   default=512)
parser.add_argument("--lr",      type=float, default=2e-4)
args = parser.parse_args()

# Detect if we're on Bridges2 (larger GPU) and bump defaults
is_bridges2 = "SLURM_JOB_ID" in os.environ
if is_bridges2:
    args.batch = args.batch if args.batch > 4 else 8
    args.rank  = args.rank  if args.rank  > 16 else 32
    print(f"Bridges2 detected — using batch={args.batch}, rank={args.rank}")

# ── Load model ────────────────────────────────────────────────────────────────

print(f"Loading {args.model} with 4-bit quantization...")
from unsloth import FastLanguageModel  # noqa: E402 (heavy import, kept late)

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=args.model,
    max_seq_length=args.seq_len,
    dtype=None,       # auto-detect (bfloat16 on Ampere+, float16 on older)
    load_in_4bit=True,
)

# ── Attach LoRA adapter ───────────────────────────────────────────────────────

print(f"Attaching LoRA (rank={args.rank})...")
model = FastLanguageModel.get_peft_model(
    model,
    r=args.rank,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=args.rank * 2,
    lora_dropout=0.0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

# ── Load and format dataset ───────────────────────────────────────────────────

from datasets import load_dataset  # noqa: E402
from unsloth.chat_templates import get_chat_template  # noqa: E402

tokenizer = get_chat_template(tokenizer, chat_template="llama-3")

raw_ds = load_dataset("json", data_files={"train": args.data}, split="train")

def format_example(batch):
    convos = batch["messages"]
    texts = [
        tokenizer.apply_chat_template(c, tokenize=False, add_generation_prompt=False)
        for c in convos
    ]
    return {"text": texts}

dataset = raw_ds.map(format_example, batched=True, remove_columns=raw_ds.column_names)
print(f"Dataset: {len(dataset):,} examples")
print(f"Sample:\n{dataset[0]['text'][:400]}\n")

# ── Train ─────────────────────────────────────────────────────────────────────

from trl import SFTTrainer  # noqa: E402
from transformers import TrainingArguments  # noqa: E402

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=args.seq_len,
    dataset_num_proc=2,
    args=TrainingArguments(
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=max(1, 8 // args.batch),
        warmup_steps=50,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        fp16=not is_bridges2,
        bf16=is_bridges2,
        logging_steps=50,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        output_dir=args.out + "_checkpoints",
        save_strategy="epoch",
    ),
)

print("Starting training...")
trainer_stats = trainer.train()
print(f"Training complete in {trainer_stats.metrics['train_runtime']:.0f}s")

# ── Save LoRA adapter ─────────────────────────────────────────────────────────

model.save_pretrained(args.out)
tokenizer.save_pretrained(args.out)
print(f"LoRA adapter saved to {args.out}/")

# ── Export to GGUF for Ollama ─────────────────────────────────────────────────

gguf_path = args.out + "_gguf"
print(f"\nExporting to GGUF (Q4_K_M) → {gguf_path} ...")
model.save_pretrained_gguf(gguf_path, tokenizer, quantization_method="q4_k_m")

gguf_file = next(
    (p for p in __import__("pathlib").Path(gguf_path).glob("*.gguf")), None
)
if gguf_file:
    print(f"\nGGUF model ready: {gguf_file}")
    print("\nTo load into Ollama (run on your Mac after downloading the .gguf):")
    print(f"  1. Copy {gguf_file.name} to this repo root")
    print(f"  2. Run: ollama create memegpt -f scripts/Modelfile")
    print(f"  3. Update backend/config.py: ollama_model = 'memegpt'")
else:
    print("Warning: could not find .gguf output file.")
