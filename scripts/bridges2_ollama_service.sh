#!/bin/bash
# ============================================================
# MemeGPT — Ollama service on PSC Bridges-2 V100-32GB
# Submit: sbatch scripts/bridges2_ollama_service.sh
# ============================================================
#SBATCH --job-name=memegpt-ollama
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=logs/ollama_%j.log
#SBATCH --error=logs/ollama_%j.log

set -e
mkdir -p logs

OLLAMA_DIR="$HOME/.ollama"
OLLAMA_BIN="$HOME/bin/ollama"
MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
PORT=11434
NODE=$(hostname -s)

echo "============================================================"
echo "Job ID:   $SLURM_JOB_ID"
echo "Node:     $NODE"
echo "GPU:      $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'V100-32')"
echo "Model:    $MODEL"
echo "============================================================"

# ── Install Ollama if not present ────────────────────────────────────────────
if [ ! -f "$OLLAMA_BIN" ]; then
    echo "Installing Ollama..."
    mkdir -p "$HOME/bin"
    curl -fsSL https://ollama.com/install.sh | OLLAMA_INSTALL_DIR="$HOME/bin" sh
fi

export PATH="$HOME/bin:$PATH"
export OLLAMA_MODELS="$OLLAMA_DIR/models"
mkdir -p "$OLLAMA_MODELS"

# ── Start Ollama server ───────────────────────────────────────────────────────
OLLAMA_HOST="0.0.0.0:$PORT" ollama serve &
OLLAMA_PID=$!
echo "Ollama PID: $OLLAMA_PID"
sleep 6

# ── Pull model (skips if already cached in $OLLAMA_MODELS) ───────────────────
echo "Pulling $MODEL ..."
ollama pull "$MODEL"
echo "Model ready."

# ── Print SSH tunnel command for local machine ────────────────────────────────
echo ""
echo "============================================================"
echo "  CONNECT from your local machine:"
echo ""
echo "  ssh -L $PORT:$NODE:$PORT -N $USER@bridges2.psc.edu"
echo ""
echo "  Then set in your local .env:"
echo "  OLLAMA_HOST=http://localhost:$PORT"
echo ""
echo "  Or for Docker stack:"
echo "  docker compose restart backend"
echo "  (OLLAMA_HOST in docker-compose.yml is already http://host.docker.internal:$PORT)"
echo "============================================================"

# ── Wait until job time limit ─────────────────────────────────────────────────
wait $OLLAMA_PID
