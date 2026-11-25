#!/usr/bin/env bash
# Leakage check of benchmark sentences against the Rasa training sets. Run from WSL.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/urdu-tts/piper1-gpl/.venv/bin/python"
"$PY" scripts/leakage_check.py "$HOME/urdu-tts/data/rasa_m/metadata.csv" "$HOME/urdu-tts/data/rasa_f/metadata.csv"
