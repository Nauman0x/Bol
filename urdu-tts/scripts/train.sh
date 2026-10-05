#!/usr/bin/env bash
# Fine-tune Piper on the prepared Urdu dataset.
#
#   scripts/train.sh smoke    # 10-minute run on 200 clips, proves the pipeline works
#   scripts/train.sh start    # full run from the stock Urdu checkpoint
#   scripts/train.sh resume   # continue from the newest good checkpoint in runs/
#   scripts/train.sh auto     # resume if a checkpoint exists, else start; restart after crashes.
#                             # This is what the Windows autostart task runs after a power cut.
#
# Run from the urdu-tts folder. Override with env vars:
#   DATA=data/s2 VOICE=ur_PK-bol-medium BATCH=16 BASE_CKPT=... scripts/train.sh start
set -euo pipefail

MODE="${1:-}"
DATA="${DATA:-data/s2}"
VOICE="${VOICE:-ur_PK-bol-medium}"
BATCH="${BATCH:-16}"
BASE_CKPT="${BASE_CKPT:-checkpoints/ur/ur_PK/fasih/medium/epoch=3206-step=383452.ckpt}"
RUNS="${RUNS:-runs}"
BACKUP_EVERY_MIN="${BACKUP_EVERY_MIN:-30}"
BACKUP_KEEP="${BACKUP_KEEP:-3}"

[ -n "${VIRTUAL_ENV:-}" ] || source piper1-gpl/.venv/bin/activate

# A checkpoint is a zip archive; one cut off by a power failure fails this check.
ckpt_ok() {
    python3 -c 'import sys, zipfile; sys.exit(zipfile.ZipFile(sys.argv[1]).testzip() is not None)' "$1" 2>/dev/null
}

# Newest checkpoint that is intact, looking at live checkpoints and backups.
newest_good_ckpt() {
    local f
    while IFS= read -r f; do
        if ckpt_ok "$f"; then
            echo "$f"
            return 0
        fi
        echo "skipping damaged checkpoint: $f" >&2
    done < <(ls -t "$RUNS"/lightning_logs/version_*/checkpoints/*.ckpt "$RUNS"/backup/*.ckpt 2>/dev/null)
    return 1
}

# Lightning keeps only the latest checkpoint. Keep a few older copies as well,
# so a checkpoint damaged mid-write still leaves something to resume from.
backup_loop() {
    local newest name
    mkdir -p "$RUNS/backup"
    while sleep "$((BACKUP_EVERY_MIN * 60))"; do
        newest="$(ls -t "$RUNS"/lightning_logs/version_*/checkpoints/*.ckpt 2>/dev/null | head -n 1)"
        [ -n "$newest" ] || continue
        name="$(basename "$newest")"
        [ -f "$RUNS/backup/$name" ] && continue
        ckpt_ok "$newest" || continue
        cp "$newest" "$RUNS/backup/.partial" && sync && mv "$RUNS/backup/.partial" "$RUNS/backup/$name"
        ls -t "$RUNS"/backup/*.ckpt | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f
    done
}

fit() {
    local csv="$1" ckpt="$2"
    shift 2
    echo "$(date '+%F %T') mode=$MODE csv=$csv batch=$BATCH checkpoint=$ckpt"
    # max_epochs -1: the base checkpoint is already past epoch 3000, so any finite
    # default would end training immediately. Stop it yourself when quality plateaus.
    "$@" python3 -m piper.train fit \
        --data.voice_name "$VOICE" \
        --data.csv_path "$csv" \
        --data.audio_dir "$DATA/wavs/" \
        --model.sample_rate 22050 \
        --data.espeak_voice "ur" \
        --data.cache_dir "$DATA/cache/" \
        --data.config_path "$RUNS/$VOICE.onnx.json" \
        --data.batch_size "$BATCH" \
        --trainer.default_root_dir "$RUNS" \
        --trainer.max_epochs -1 \
        --ckpt_path "$ckpt"
}

CSV="$DATA/metadata.csv"
[ "$MODE" = smoke ] && { CSV="$DATA/metadata_smoke.csv"; RUNS="$RUNS/smoke"; }
case "$MODE" in smoke | start | resume | auto) ;; *)
    echo "usage: scripts/train.sh smoke|start|resume|auto" >&2
    exit 2
    ;;
esac
[ -f "$CSV" ] || { echo "Missing $CSV. Run scripts/prepare_dataset.py first." >&2; exit 1; }
[ -f "$BASE_CKPT" ] || { echo "Missing base checkpoint $BASE_CKPT." >&2; exit 1; }
mkdir -p "$RUNS"

# One training process per run directory (the autostart task and a manual start could collide).
exec 9>"$RUNS/.train.lock"
flock -n 9 || { echo "Training is already running for $RUNS." >&2; exit 0; }

if [ "$MODE" = smoke ]; then
    # SIGINT lets Lightning shut down cleanly; exit code 124 is the expected timeout.
    fit "$CSV" "$BASE_CKPT" timeout --signal=INT 600
    exit
fi

backup_loop &
trap 'kill %1 2>/dev/null || true' EXIT

case "$MODE" in
    start)
        fit "$CSV" "$BASE_CKPT"
        ;;
    resume)
        CKPT="$(newest_good_ckpt)" || { echo "No usable checkpoint under $RUNS to resume from." >&2; exit 1; }
        fit "$CSV" "$CKPT"
        ;;
    auto)
        quick_failures=0
        while true; do
            CKPT="$(newest_good_ckpt)" || CKPT="$BASE_CKPT"
            began=$SECONDS
            code=0
            fit "$CSV" "$CKPT" || code=$?
            # 0 = finished, 130 = Ctrl-C: both mean stop, not crash.
            if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then
                break
            fi
            if [ $((SECONDS - began)) -lt 300 ]; then
                quick_failures=$((quick_failures + 1))
            else
                quick_failures=0
            fi
            if [ "$quick_failures" -ge 5 ]; then
                echo "Training failed 5 times in a row within 5 minutes each. Giving up; see the log above." >&2
                exit 1
            fi
            echo "$(date '+%F %T') training exited with code $code, restarting in 30 s" >&2
            sleep 30
        done
        ;;
esac
