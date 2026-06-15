#!/bin/bash
#SBATCH --job-name=memegpt-finetune
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64GB
#SBATCH --time=04:00:00
#SBATCH --output=logs/finetune_%j.out
#SBATCH --error=logs/finetune_%j.err

# Pittsburgh Supercomputing Center — Bridges-2 SLURM job
# Submits to GPU-shared partition (V100 32GB) — adjust partition for A100s:
#   --partition=GPU --gres=gpu:a100:1 (if you have allocation)
#
# Usage:
#   mkdir -p logs
#   sbatch scripts/bridges2_job.sh
#
# Monitor:
#   squeue -u $USER
#   tail -f logs/finetune_<JOB_ID>.out

echo "Job $SLURM_JOB_ID starting on $(hostname) at $(date)"

# ── Load modules ──────────────────────────────────────────────────────────────
module load cuda/12.1
module load anaconda3

# ── Activate environment ──────────────────────────────────────────────────────
# Create once with:
#   conda create -n memegpt python=3.11
#   conda activate memegpt
#   pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
#   pip install --no-deps "xformers<0.0.27" "trl<0.9.0" peft accelerate bitsandbytes
#   pip install datasets transformers

conda activate memegpt

# ── Navigate to project ───────────────────────────────────────────────────────
cd $PROJECT/memegpt   # adjust to your Bridges2 project path

# ── Prepare dataset (if not already done) ────────────────────────────────────
# python3 scripts/prepare_finetune_dataset.py \
#     --csv data/imgflip_data.csv \
#     --out scripts/memegpt_train.jsonl \
#     --limit 50000

# ── Fine-tune ─────────────────────────────────────────────────────────────────
python3 scripts/finetune_unsloth.py \
    --data scripts/memegpt_train.jsonl \
    --out  scripts/memegpt_lora \
    --epochs 3 \
    --batch 8 \
    --rank 32 \
    --seq-len 512

echo "Job completed at $(date)"
