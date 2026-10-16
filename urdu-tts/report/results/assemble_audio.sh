#!/usr/bin/env bash
# Copies the final listening material from ~/urdu-tts/samples (WSL) into report/audio.
set -u
S=~/urdu-tts/samples
A=/mnt/c/Users/Ehtesham/Bol/urdu-tts/report/audio
rm -rf "$A"; mkdir -p "$A"

for v in male female; do
  d="$A/${v}_voice"; src="$S/final_$v"
  mkdir -p "$d"
  cp -r "$src/1_original_model"       "$d/1_original_piper_voice"
  cp -r "$src/2_original_rasa_voice"  "$d/2_real_human_recordings"
  cp -r "$src/3_ours"                 "$d/3_our_trained_voice"
  cp "$src/sentences.txt"             "$d/sentences.txt"
  cp "$src/long.wav"                  "$d/long_paragraph_our_voice.wav"
  cp -r "$src/test_lines"             "$d/casual_lines_our_voice"
done

# How the same ~30 s customer-support paragraph improved over the project.
t="$A/progress_timeline"; mkdir -p "$t"
n=0
add() {  # file, label
  n=$((n+1))
  if [ -f "$1" ]; then cp "$1" "$t/$(printf %02d $n)_$2.wav"; else echo "MISSING: $1 ($2)"; n=$((n-1)); fi
}
add $S/long/long_stock.wav                              original_piper_voice
add $S/long/long_latest.wav                             podcast_data_full_finetune_FAILED_garbled_words
add $S/compare_1912/long_v3_frozen_text_epoch63.wav     podcast_data_frozen_encoder_distorted
add $S/compare_1912/long_v4_frozen_text_and_decoder_epoch109.wav podcast_data_frozen_decoder_worse
add $S/rasa_epoch4/long.wav                             studio_data_male_epoch4
add $S/rasa_epoch21/long_default.wav                    studio_data_male_epoch21
add $S/rasa_epoch47/long.wav                            studio_data_male_epoch47
add $S/final_male/long.wav                              studio_data_male_FINAL_epoch119
add $S/final_female/long.wav                            studio_data_female_FINAL_epoch119
ls "$t"; du -sh "$A"; find "$A" -name '*.wav' | wc -l
