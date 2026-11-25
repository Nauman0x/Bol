#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"$HOME/urdu-tts/piper1-gpl/.venv/bin/python" scripts/prep_listening.py
