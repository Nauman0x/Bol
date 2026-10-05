#!/usr/bin/env bash
# Export a training checkpoint to a deployable Piper voice (.onnx + .onnx.json).
#
#   scripts/export.sh                      # newest checkpoint in runs/
#   scripts/export.sh path/to/best.ckpt
set -euo pipefail

VOICE="${VOICE:-ur_PK-bol-medium}"
RUNS="${RUNS:-runs}"
CKPT="${1:-$(ls -t "$RUNS"/lightning_logs/version_*/checkpoints/*.ckpt 2>/dev/null | head -n 1)}"
OUT="${OUT:-export/$VOICE.onnx}"

[ -f "$CKPT" ] || { echo "Checkpoint not found: '$CKPT'" >&2; exit 1; }
[ -f "$RUNS/$VOICE.onnx.json" ] || { echo "Missing voice config $RUNS/$VOICE.onnx.json" >&2; exit 1; }

[ -n "${VIRTUAL_ENV:-}" ] || source piper1-gpl/.venv/bin/activate

mkdir -p "$(dirname "$OUT")"
# piper_export_onnx.py: Piper's exporter with torch's TorchScript exporter (the default one fails on VITS).
python3 scripts/piper_export_onnx.py --checkpoint "$CKPT" --output-file "$OUT"
cp "$RUNS/$VOICE.onnx.json" "$OUT.json"

echo "آج موسم بہت اچھا ہے۔" | python3 -m piper -m "$OUT" -f "$(dirname "$OUT")/test.wav"
echo "Exported $OUT and $OUT.json from $CKPT; test audio in $(dirname "$OUT")/test.wav"
