#!/usr/bin/env bash
# Serve Qwen2.5 Q4_K_M + the c1 LoRA, run latency (warm, cold) and probe-gen for the tuned model.
cd "$(dirname "$0")/.."
export LLAMA_EXTRA="--lora models/lora-c1/lora-c1-f16.gguf"
bash scripts/run_local.sh models/qwen25/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf qwen25-c1 qwen25_c1
