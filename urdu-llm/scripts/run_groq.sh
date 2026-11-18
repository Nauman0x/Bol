#!/usr/bin/env bash
# run_groq.sh : Groq hosted-Qwen3 reference (arm A'). Key is read from bol/.env into the environment, never printed.
cd "$(dirname "$0")/.."
export GROQ_API_KEY=$(grep -E '^GROQ_API_KEY=' /mnt/c/Users/Ehtesham/Bol/bol/.env | head -1 | cut -d= -f2- | tr -d '\r"' )
source .venv-serve/bin/activate
A=(--base-url https://api.groq.com/openai/v1 --model qwen/qwen3.8-27b --tag groq-qwen38-27b --key-env GROQ_API_KEY --reasoning-effort none)
python scripts/bench_models.py latency "${A[@]}" --concurrency 1 --requests 20 --warmup 2 2>&1 | tail -4
python scripts/bench_models.py probe-gen "${A[@]}" 2>&1 | tail -3
