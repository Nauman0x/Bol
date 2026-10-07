# Urdu TTS for BOL

Fine-tunes a single-speaker Urdu voice with [Piper](https://github.com/OHF-Voice/piper1-gpl) (VITS), starting from the stock `ur_PK-fasih-medium` checkpoint, on one speaker of the [URDUTTS](https://github.com/KAABSHAHID/URDUTTS) dataset. The result is an `.onnx` voice that runs on CPU.

**Non-commercial only.** URDUTTS is CC BY-NC 4.0 and the base checkpoint's training data has no stated licence. Piper's code is GPL-3.0, so run it as its own service and do not import it into BOL code.

## Requirements (training PC)

- Windows 10/11 with an NVIDIA GPU (10-12 GB VRAM), recent NVIDIA driver, virtualisation enabled in BIOS
- 16 GB RAM or more, about 60 GB free disk
- Roughly 2-3 days of continuous training (estimate)

## 1. WSL2

In an administrator PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot if asked, create a Linux user, then check the GPU is visible:

```powershell
wsl nvidia-smi
```

## 2. Setup

Copy this folder into the Linux filesystem (training from `/mnt/c` is slow) and run setup:

```sh
cp -r /mnt/c/path/to/urdu-tts ~/urdu-tts
cd ~/urdu-tts
bash setup_wsl.sh
```

This installs Piper with its training extras, checks CUDA, runs the unit tests, downloads the stock Urdu voice and its checkpoint, and writes baseline audio to `samples/baseline/`. Listen to it: that is the quality to beat.

In every new shell after this:

```sh
cd ~/urdu-tts
source piper1-gpl/.venv/bin/activate
export PYTHONPATH=scripts
```

## 3. Download the dataset

The public release is [`kaab4321/UrduTTS`](https://huggingface.co/datasets/kaab4321/UrduTTS) (not gated): about 29 GB of 44.1 kHz clips in ~500 MB shards. It has four male speakers but **no speaker labels**, so the script recovers them by clustering speaker embeddings.

```sh
python scripts/download_data.py --inspect                 # splits, shard sizes, columns
python scripts/download_data.py --cluster --shards 2      # ~1 GB; finds the 4 voices
```

`--cluster` saves the voice centroids to `data/voices.npz` and writes the 20 most typical clips of each voice to `data/listen_v1` ... `data/listen_v4` (in Windows: `\\wsl$\Ubuntu-24.04\home\<user>\urdu-tts\data\`). Listen, pick the cleaner, more pleasant voice, then extract it:

```sh
python scripts/download_data.py --voice 2 --out data/raw_v2 --hours 15
```

This downloads shards one at a time and keeps only clips that clearly match that voice, stopping at `--hours` of audio. Rerun the same command to resume after an interruption. Use `data/raw_v2` / `data/v2` in place of `data/raw_s2` / `data/s2` below, and pass `DATA=data/v2` to `train.sh`.

### Clean casual voice: Rasa (what this project uses)

[`ai4bharat/Rasa`](https://huggingface.co/datasets/ai4bharat/Rasa) (CC BY 4.0, gated: accept its terms and `hf auth login`) has studio recordings of one male and one female Urdu voice, about 26 h each, in several styles. The conversational, emotion and assistant-command styles give about 11 h of casual-register speech per voice, with English loanwords written in Urdu script:

```sh
python scripts/download_rasa.py --inspect
python scripts/download_rasa.py --gender Male --exclude WIKI,BOOK,NEWS,PROPER --out data/raw_rasa_m
python scripts/prepare_dataset.py --raw data/raw_rasa_m --out data/rasa_m
cat > train.env <<'EOF'
DATA=data/rasa_m
RUNS=runs_rasa
BATCH=12
MAX_EPOCHS=120
EXTRA_ARGS=--model.warmup_epochs 3 --model.init_lr_ratio 0.1
EOF
```

Whisper CER after 4 epochs: 7.0% on held-out Rasa sentences (stock voice 7.2%) and 2.3% on casual code-switched sentences (stock 6.0%). Because Rasa spells English loanwords in Urdu script, `synth.py` converts English words in Latin script with `lexicon/english_ur.tsv`; use the same lexicon wherever this voice is deployed.

### Podcast voice (tried first; not recommended)

URDUTTS is formal audiobook narration. For everyday, code-switched Urdu use one speaker of [`ASLP-lab/UrduSpeech`](https://huggingface.co/datasets/ASLP-lab/UrduSpeech) (CC BY 4.0; podcasts, interviews, vlogs). Speakers are diarized per category; the largest have 1-1.5 h. This project uses podcast `SPEAKER_0038`:

```sh
python scripts/download_aslp.py --category podcast --speaker SPEAKER_0038 --out data/raw_p38
python scripts/prepare_dataset.py --raw data/raw_p38 --out data/p38 --allow-latin --max-sec 30 --test-size 20
printf 'DATA=data/p38\nBATCH=8\n' > train.env
```

Then drop clips whose machine-made transcript does not match the audio (some include words from before or after the clip, which teaches the model to mumble), and train on the result:

```sh
python scripts/eval_cer.py data/p38 --index data/p38/metadata.csv --save data/p38/cer_train.tsv
python scripts/filter_dataset.py --data data/p38 --cer data/p38/cer_train.tsv --out data/p38c
cat > train.env <<'EOF'
DATA=data/p38c
RUNS=runs_v3
BATCH=8
MAX_EPOCHS=300
FREEZE=model_g.enc_p,model_g.dp
EXTRA_ARGS=--model.warmup_epochs 5 --model.init_lr_ratio 0.1
EOF
```

`FREEZE` keeps the base voice's text encoder and duration predictor fixed, so pronunciation and timing stay as good as the stock voice and only the sound of the voice is trained. Without it, every run on this 1-hour dataset garbled words (Whisper CER 59-69% against 33% for the stock voice; 28% with it).

Starting from the base voice, `train.sh` copies only its weights (`--model.warmstart_ckpt`), so the run gets a fresh optimizer, a warm-up and a learning rate that anneals over `MAX_EPOCHS`. Resuming the base voice's own training state instead (`--ckpt_path`) garbled pronunciation within two epochs on this 1-hour dataset. `EXTRA_ARGS` is written without quotes.

`download_aslp.py` drops clips that do not sound like the speaker (diarization errors; see `speaker_check.tsv`). `--allow-latin` keeps English words written in Latin script, which espeak-ng reads as English inside Urdu sentences. `--max-sec 30` keeps the long podcast turns, which need `BATCH=8` on a 12 GB card. `train.env` makes every `train.sh` run, including the autostart task, use this dataset.

## 4. Prepare

```sh
python scripts/prepare_dataset.py --raw data/raw_s2 --out data/s2
```

Resamples to 22.05 kHz mono, trims silence, normalises loudness, normalises the Urdu text (digits to words, Arabic letters to Urdu ones, punctuation), and drops clips that are too short, too long, clipped, contain Latin text, or whose text length does not fit the audio length. It holds out 100 utterances in `data/s2/test.csv`. Read the summary line and skim `rejected.tsv`; if a large share is rejected, look at why before training.

## 5. Train

Smoke run first (10 minutes on 200 clips):

```sh
scripts/train.sh smoke
```

It should log falling losses and leave a checkpoint under `runs/smoke/lightning_logs/`; it stops itself after 10 minutes. Check that resuming works: `RUNS=runs/smoke scripts/train.sh resume` should print `checkpoint=runs/smoke/...`; stop it with Ctrl-C. Then the real run, inside tmux so it survives closing the terminal:

```sh
tmux new -s train
scripts/train.sh start
```

Detach with `Ctrl-b d`, re-attach with `tmux attach -t train`. Watch progress with `tensorboard --logdir runs/lightning_logs`.

- Out of memory: `BATCH=12 scripts/train.sh start` (or 8).
- Spare VRAM in `nvidia-smi`: try `BATCH=24`.
- **Interrupted** (reboot, crash, Ctrl-C): `scripts/train.sh resume` continues from the newest intact checkpoint.

Stop Windows from sleeping while this runs.

### Surviving a power cut

Training saves a checkpoint at the end of every epoch, and `train.sh` copies one to `runs/backup/` every 30 minutes, keeping the last 3. After a power cut it continues from the newest checkpoint that is not damaged, so you lose the epoch that was in progress, not the run. A checkpoint that was half-written when the power went is detected and skipped.

To make the restart happen without you, instead of starting training in tmux:

1. In Windows PowerShell, from this folder: `powershell -ExecutionPolicy Bypass -File install_autostart.ps1`, then `Start-ScheduledTask -TaskName UrduTTS-Train`. From now on training resumes every time you log on to Windows.
2. BIOS: set "Restore on AC Power Loss" (or "AC Back") to "Power On", so the PC boots when power returns.
3. Windows: turn on automatic sign-in (`netplwiz`), so the logon happens without you. Without this, training resumes when you next sign in.

Follow progress with `wsl -d Ubuntu-24.04 -- tail -f ~/urdu-tts/runs/train.log`. Stop training with `wsl -d Ubuntu-24.04 -- pkill -INT -f piper.train`. When training is finished, remove the task, or it will start training again at the next logon: `powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove`.

Test it once before relying on it: with training running, restart the PC and check that `train.log` shows it continuing from a checkpoint in `runs/`, not from the base checkpoint.

## 6. Evaluate

Listen every few hours:

```sh
CKPT=$(ls -t runs/lightning_logs/version_*/checkpoints/*.ckpt | head -n 1)
python scripts/synth.py --model "$CKPT" --config runs/ur_PK-bol-medium.onnx.json \
    --text-file sentences/listen.txt --out samples/latest
```

Measure intelligibility on the held-out text, against the stock voice:

```sh
python scripts/synth.py --model voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx \
    --text-file data/s2/test.csv --out samples/test_baseline
python scripts/synth.py --model "$CKPT" --config runs/ur_PK-bol-medium.onnx.json \
    --text-file data/s2/test.csv --out samples/test_ours
python scripts/eval_cer.py samples/test_baseline
python scripts/eval_cer.py samples/test_ours
```

`eval_cer.py` loads Whisper large-v3 on the GPU (about 4 GB VRAM). If training is using the card, add `--device cpu` (slow) or pause training. Stop training when listening and CER have stopped improving across two checks.

Words that are consistently mispronounced: add them to a lexicon file (`word<TAB>diacritised spelling` per line) and pass `--lexicon` to `prepare_dataset.py` and `synth.py`.

## 7. Export

```sh
scripts/export.sh                 # newest checkpoint, or pass a path
```

Produces `export/ur_PK-bol-medium.onnx` and `.onnx.json`. Those two files are the voice. Anywhere with `pip install piper-tts`:

```sh
echo "آج موسم بہت اچھا ہے۔" | python -m piper -m ur_PK-bol-medium.onnx -f out.wav
```

Pass text through `scripts/normalize_ur.py` first, as training did.

## 8. Use the voices in BOL

BOL's `piper` TTS provider talks to a small HTTP server that loads every voice in `export/`, normalises the text the same way as training (numbers, English words via `lexicon/english_ur.tsv`, pronunciation fixes via `lexicon/urdu_fix.tsv` and `lexicon/phonemes.tsv`) and streams 16-bit PCM one sentence at a time. It runs separately because Piper is GPL-3.0; BOL only calls it over HTTP.

```sh
python server/serve.py --voices export --port 8030     # piper venv active, from this folder
curl localhost:8030/voices
```

A voice file `export/ur_PK-bol_rasa_female-medium.onnx` is served as voice id `rasa_female`. In BOL's `.env` set `PIPER_BASE_URL=http://localhost:8030` (WSL forwards the port to Windows), then pick **BOL Urdu (self-hosted Piper)**, language **Urdu**, and a voice in the agent form. The agent is told to answer in Urdu script, since the voice cannot read Roman Urdu.

## 9. Your own voice (later)

1. Record 1-2 hours: quiet room, same microphone and distance throughout, 44.1 or 48 kHz mono WAV, one sentence per file, 3-12 seconds each, steady neutral delivery.
2. Put the files in `data/raw_me/wavs/` and write `data/raw_me/raw.tsv` (`file.wav<TAB>sentence`).
3. `python scripts/prepare_dataset.py --raw data/raw_me --out data/me`
4. `DATA=data/me VOICE=ur_PK-me-medium RUNS=runs_me BASE_CKPT=<best checkpoint from step 5> scripts/train.sh start`

Expect a few hours of training. Only train on a voice you have consent to use.

## Unverified at the time of writing

These are checked by the steps above rather than assumed:

- How cleanly the four URDUTTS voices separate (`--cluster` prints a silhouette score and per-voice similarity; listen to the samples).
- Training starts through `scripts/piper_train_fit.py`, which is `piper.train` without its `val_mos` checkpoint: that needs torchaudio, which has no build for the torch version RTX 50xx cards require, and Lightning aborts after the first epoch without it.
- Training time and VRAM figures are estimates.
