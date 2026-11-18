#!/usr/bin/env bash
# wait_llama.sh <log> [port] : block until llama-server /health is OK, or report why not.
LOG="$1"; PORT="${2:-8000}"
for _ in $(seq 1 100); do curl -sf "localhost:$PORT/health" >/dev/null && { echo READY; break; }; pgrep -f '[l]lama-server' >/dev/null || { echo DIED; break; }; sleep 3; done
grep -iE "error|offloaded|failed|CUDA0 model" "$LOG" | head -6 | cut -c1-200
nvidia-smi --query-gpu=memory.used --format=csv,noheader
