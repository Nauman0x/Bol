#!/usr/bin/env bash
# run_local.sh <gguf> <alias> <tag> [bench flags e.g. --no-think] : serve one GGUF, run warm+cold latency and probe-gen, stop it.
cd "$(dirname "$0")/.."
GGUF="$1"; ALIAS="$2"; TAG="$3"; shift 3
pkill -x llama-server; sleep 3
setsid nohup bash scripts/llama_serve.sh "$GGUF" "$ALIAS" 8000 > "serve_$TAG.log" 2>&1 < /dev/null &
bash scripts/wait_llama.sh "serve_$TAG.log"
source .venv-serve/bin/activate
python scripts/bench_models.py latency --model "$ALIAS" --tag "$TAG" "$@" 2>&1 | tail -3
python scripts/bench_models.py latency --model "$ALIAS" --tag "$TAG" --cold "$@" 2>&1 | tail -3
python scripts/bench_models.py probe-gen --model "$ALIAS" --tag "$TAG" "$@" 2>&1 | tail -1
pkill -x llama-server
