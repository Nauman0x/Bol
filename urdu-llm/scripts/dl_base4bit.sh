#!/usr/bin/env bash
# dl_base4bit.sh : download the pre-quantised bnb-4bit Qwen2.5-7B-Instruct (QLoRA base, ~5.5 GB) with retry.
cd "$(dirname "$0")/.."
source .venv-serve/bin/activate; export HF_HUB_DISABLE_XET=1
until hf download unsloth/Qwen2.5-7B-Instruct-bnb-4bit --local-dir models/qwen25-bnb4; do echo retry; sleep 5; done
touch dl_base4bit.flag; echo DONE
