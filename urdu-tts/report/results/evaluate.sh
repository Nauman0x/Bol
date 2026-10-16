#!/usr/bin/env bash
# Final evaluation for the project report (run inside WSL, piper venv, from ~/urdu-tts).
#
#   bash report/results/evaluate.sh > results.txt
#
# For each Rasa voice, on its 100 held-out test sentences (never trained on):
# Whisper large-v3-turbo transcribes (a) the real human recording, (b) the original
# Piper Urdu voice, (c) our fine-tuned voice, and the character error rate (CER)
# against the sentence text is reported. Lower = easier to understand. Whisper has
# its own errors on Urdu, so compare rows with each other, never with 0.
# Also: the 20 casual one-line test sentences, and synthesis speed.
set -u
cd ~/urdu-tts && source piper1-gpl/.venv/bin/activate && export PYTHONPATH=scripts
W=openai/whisper-large-v3-turbo
STOCK=voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx
O=/tmp/final_eval; rm -rf $O; mkdir -p $O
cer() { python scripts/eval_cer.py "$@" --model $W --worst 0 2>&1 | grep -E 'utterances, CER'; }

for g in male female; do
  d=data/rasa_${g:0:1}; ours=export/ur_PK-bol_rasa_${g}-medium.onnx
  echo "## $g voice, 100 held-out Rasa sentences"
  echo -n "real_recording: "; cer $d --index $d/test.csv
  python scripts/synth.py --model $STOCK --text-file $d/test.csv --out $O/stock_$g 2>&1 | grep -E 'real-time factor' | sed 's/^/stock_speed: /'
  echo -n "original_piper_voice: "; cer $O/stock_$g
  python scripts/synth.py --model $ours --text-file $d/test.csv --out $O/ours_$g 2>&1 | grep -E 'real-time factor' | sed 's/^/ours_speed: /'
  echo -n "our_voice: "; cer $O/ours_$g
done

echo "## 20 casual one-line sentences (mixed Urdu/English), sentences/test_lines.txt"
python scripts/synth.py --model $STOCK --text-file sentences/test_lines.txt --out $O/stock_lines >/dev/null 2>&1
echo -n "original_piper_voice: "; cer $O/stock_lines
for g in male female; do
  python scripts/synth.py --model export/ur_PK-bol_rasa_${g}-medium.onnx --text-file sentences/test_lines.txt --out $O/lines_$g >/dev/null 2>&1
  echo -n "our_${g}_voice: "; cer $O/lines_$g
done
