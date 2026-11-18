#!/usr/bin/env bash
# Serve one model with vLLM on the 12 GB card (run inside WSL, .venv-serve active).
#   scripts/serve.sh <hf-model> [quant: fp8|awq|none] [port]
# Stop it before training: one card is shared by serving and training.
set -euo pipefail
MODEL="$1"; QUANT="${2:-fp8}"; PORT="${3:-8000}"
Q=(); [ "$QUANT" != none ] && Q=(--quantization "$QUANT")
exec vllm serve "$MODEL" "${Q[@]}" --port "$PORT" \
  --max-model-len 2048 --max-num-seqs 8 --gpu-memory-utilization "${GPU_UTIL:-0.85}" \
  --enable-prefix-caching --served-model-name "$MODEL"
