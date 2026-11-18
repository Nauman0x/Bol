#!/usr/bin/env bash
# llama_serve.sh <gguf> <alias> [port] [extra llama-server args...] : serve one GGUF with llama.cpp (WSL).
set -euo pipefail
cd "$(dirname "$0")/.."
GGUF="$1"; ALIAS="$2"; PORT="${3:-8000}"; shift 3 || shift $#
S=$(find llama.cpp -name llama-server | head -1)
export LD_LIBRARY_PATH="$(dirname "$S"):$(dirname "$S")/../cudart-llama-b12283-bin-ubuntu-cuda-12.8-x64:${LD_LIBRARY_PATH:-}"
exec "$S" -m "$GGUF" -ngl 99 -c 8192 --parallel 4 --port "$PORT" -a "$ALIAS" ${LLAMA_JINJA---jinja} ${LLAMA_EXTRA:-} "$@"
