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

```sh
python scripts/download_data.py --inspect
```

If it says the dataset is gated, accept the terms on the Hugging Face page and run `hf auth login`. Check the printed columns and speaker names, then pull a few clips of each candidate speaker and listen:

```sh
python scripts/download_data.py --speaker 1 --limit 20 --out data/listen_s1
python scripts/download_data.py --speaker 2 --limit 20 --out data/listen_s2
```

The speaker value must match what `--inspect` printed. Pick the cleaner, more pleasant voice, then download it in full:

```sh
python scripts/download_data.py --speaker 2 --out data/raw_s2
```

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

It should log falling losses and leave a checkpoint under `runs/smoke/lightning_logs/`. Exit code 124 is the expected timeout. Then the real run, inside tmux so it survives closing the terminal:

```sh
tmux new -s train
scripts/train.sh start
```

Detach with `Ctrl-b d`, re-attach with `tmux attach -t train`. Watch progress with `tensorboard --logdir runs/lightning_logs`.

- Out of memory: `BATCH=12 scripts/train.sh start` (or 8).
- Spare VRAM in `nvidia-smi`: try `BATCH=24`.
- **Interrupted** (reboot, crash, Ctrl-C): `scripts/train.sh resume` continues from the newest checkpoint.
- Copy the newest checkpoint somewhere safe about twice a day.

Stop Windows from sleeping while this runs.

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

## 8. Your own voice (later)

1. Record 1-2 hours: quiet room, same microphone and distance throughout, 44.1 or 48 kHz mono WAV, one sentence per file, 3-12 seconds each, steady neutral delivery.
2. Put the files in `data/raw_me/wavs/` and write `data/raw_me/raw.tsv` (`file.wav<TAB>sentence`).
3. `python scripts/prepare_dataset.py --raw data/raw_me --out data/me`
4. `DATA=data/me VOICE=ur_PK-me-medium RUNS=runs_me BASE_CKPT=<best checkpoint from step 5> scripts/train.sh start`

Expect a few hours of training. Only train on a voice you have consent to use.

## Unverified at the time of writing

These are checked by the steps above rather than assumed:

- URDUTTS column names and whether the Hugging Face repo is gated (`--inspect` shows both).
- Piper's training flags beyond those in its [TRAINING.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md): `train.sh` also passes the standard Lightning flags `--trainer.default_root_dir` and `--trainer.max_epochs`. If the smoke run rejects a flag, check `python3 -m piper.train fit --help`.
- Training time and VRAM figures are estimates.
