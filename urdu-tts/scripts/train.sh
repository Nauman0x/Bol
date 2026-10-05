#!/usr/bin/env bash
# Fine-tune Piper on the prepared Urdu dataset.
#
#   scripts/train.sh smoke    # 10-minute run on 200 clips, proves the pipeline works
#   scripts/train.sh start    # full run from the stock Urdu checkpoint
#   scripts/train.sh resume   # continue from the newest checkpoint in runs/
#
# Run from the urdu-tts folder with the Piper venv active. Override with env vars:
#   DATA=data/s2 VOICE=ur_PK-bol-medium BATCH=16 BASE_CKPT=... scripts/train.sh start
set -euo pipefail

MODE="${1:-}"
DATA="${DATA:-data/s2}"
VOICE="${VOICE:-ur_PK-bol-medium}"
BATCH="${BATCH:-16}"
BASE_CKPT="${BASE_CKPT:-checkpoints/ur/ur_PK/fasih/medium/epoch=3206-step=383452.ckpt}"
RUNS="${RUNS:-runs}"

newest_ckpt() {
    ls -t "$RUNS"/lightning_logs/version_*/checkpoints/*.ckpt 2>/dev/null | head -n 1
}

CSV="$DATA/metadata.csv"
PREFIX=()
case "$MODE" in
    smoke)
        CSV="$DATA/metadata_smoke.csv"
        RUNS="$RUNS/smoke"
        CKPT="$BASE_CKPT"
        # SIGINT lets Lightning shut down cleanly; exit code 124 is the expected timeout.
        PREFIX=(timeout --signal=INT 600)
        ;;
    start)
        CKPT="$BASE_CKPT"
        ;;
    resume)
        CKPT="$(newest_ckpt)"
        [ -n "$CKPT" ] || { echo "No checkpoint under $RUNS/lightning_logs to resume from." >&2; exit 1; }
        ;;
    *)
        echo "usage: scripts/train.sh smoke|start|resume" >&2
        exit 2
        ;;
esac

[ -f "$CSV" ] || { echo "Missing $CSV. Run scripts/prepare_dataset.py first." >&2; exit 1; }
[ -f "$CKPT" ] || { echo "Missing checkpoint $CKPT." >&2; exit 1; }
mkdir -p "$RUNS"
echo "mode=$MODE csv=$CSV batch=$BATCH checkpoint=$CKPT"

# max_epochs -1: the base checkpoint is already past epoch 3000, so any finite
# default would end training immediately. Stop it yourself when quality plateaus.
"${PREFIX[@]}" python3 -m piper.train fit \
    --data.voice_name "$VOICE" \
    --data.csv_path "$CSV" \
    --data.audio_dir "$DATA/wavs/" \
    --model.sample_rate 22050 \
    --data.espeak_voice "ur" \
    --data.cache_dir "$DATA/cache/" \
    --data.config_path "$RUNS/$VOICE.onnx.json" \
    --data.batch_size "$BATCH" \
    --trainer.default_root_dir "$RUNS" \
    --trainer.max_epochs -1 \
    --ckpt_path "$CKPT"
