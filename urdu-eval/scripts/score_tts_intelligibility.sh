#!/usr/bin/env bash
# Whisper CER/WER of each synthesised system, same protocol as the human-recording ASR run.
# Run from WSL:  bash scripts/score_tts_intelligibility.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/urdu-tts/piper1-gpl/.venv/bin/python"
for s in stock_fasih bol_rasa_male bol_rasa_female; do
  echo "=== $s"
  "$PY" scripts/eval_asr.py --model openai/whisper-large-v3-turbo \
    --manifest "data/tts_manifest_${s}.tsv" --tag "tts_${s}" 2>&1 \
    | grep -E '^(ALL|casual|business|numbers|codeswitch)'
done
