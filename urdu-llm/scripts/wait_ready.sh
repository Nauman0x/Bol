#!/usr/bin/env bash
# wait_ready.sh <logfile> [port] : block until the vLLM server answers /health, or report why it died.
LOG="$1"; PORT="${2:-8000}"
for _ in $(seq 1 120); do
  curl -sf "localhost:$PORT/health" >/dev/null && { echo READY; break; }
  pgrep -f 'vllm serve' >/dev/null || { echo DIED; break; }
  sleep 5
done
grep -iE 'error|out of memory|Application startup|Model loading took|KV cache' "$LOG" | tail -8 | cut -c1-250
