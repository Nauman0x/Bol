#!/usr/bin/env bash
# train_when_ready.sh : wait for the base download, then train the LoRA and generate base-vs-tuned eval replies.
cd "$(dirname "$0")/.."
until [ -f dl_base4bit.flag ]; do sleep 10; done
source .venv-train/bin/activate
python scripts/train_sft.py --epochs 3 > train_c1.log 2>&1 && python scripts/gen_eval.py > gen_eval.log 2>&1
touch train_done.flag; echo FINISHED >> train_c1.log
