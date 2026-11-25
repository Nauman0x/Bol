#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"$HOME/urdu-tts/piper1-gpl/.venv/bin/python" scripts/eval_asr.py --model openai/whisper-large-v3-turbo \
  --manifest data/anchor_manifest.tsv --tag listening_anchor 2>&1 | grep -E '^(ALL)'
