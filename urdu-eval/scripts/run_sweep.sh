#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SWEEP_DEVICE="${SWEEP_DEVICE:-cpu}" "$HOME/urdu-tts/piper1-gpl/.venv/bin/python" scripts/sweep_esha.py 2>&1 | grep -v -E "Loading weights|[Ww]arn|pipelines sequentially"
