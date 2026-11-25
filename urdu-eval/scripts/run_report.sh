#!/usr/bin/env bash
# Report half: synth with the settings chosen on the tune half, then score all four systems. Run from WSL.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/urdu-tts/piper1-gpl/.venv/bin/python"
CK=$(ls "$HOME"/urdu-tts/runs_esha/lightning_logs/version_2/checkpoints/epoch=110-*.ckpt)
"$PY" scripts/synth_esha.py --half report --ckpt "$CK" --noise-scale 0.4 --noise-w 1.0 2>&1 | grep -v -i warn
for s in esha_real esha_voice bol_rasa_female stock_fasih; do
  echo "=== $s"
  "$PY" scripts/eval_asr.py --model openai/whisper-large-v3-turbo \
    --manifest "data/esha_manifest_${s}.tsv" --tag "esha_report_${s}" 2>&1 | grep -E '^(ALL)'
done
