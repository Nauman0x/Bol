#!/usr/bin/env bash
# Synthesise Esha's held-out sentences with each system, then score all with Whisper. Run from WSL.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/urdu-tts/piper1-gpl/.venv/bin/python"
"$PY" scripts/synth_esha.py "$@" 2>&1 | grep -v -i warn
for s in esha_real esha_voice bol_rasa_female stock_fasih; do
  echo "=== $s"
  "$PY" scripts/eval_asr.py --model openai/whisper-large-v3-turbo \
    --manifest "data/esha_manifest_${s}.tsv" --tag "esha_${s}" 2>&1 | grep -E '^(ALL)'
done
