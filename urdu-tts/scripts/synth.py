"""Synthesise Urdu sentences with a Piper voice (.onnx) or a training checkpoint (.ckpt).

    python scripts/synth.py --model voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx \
        --text-file sentences/listen.txt --out samples/baseline
    python scripts/synth.py --model "runs/lightning_logs/version_0/checkpoints/epoch=....ckpt" \
        --config runs/ur_PK-bol-medium.onnx.json --text-file data/s2/test.csv --out samples/test

--text-file is one sentence per line, or a Piper csv (file.wav|text).
Writes <out>/0001.wav ... and <out>/index.tsv (file<TAB>text) for eval_cer.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

from piper import PiperVoice

from normalize_ur import load_lexicon, normalize


def export_checkpoint(ckpt: Path, config: Path) -> Path:
    preview = Path("runs/preview")
    preview.mkdir(parents=True, exist_ok=True)
    onnx = preview / (ckpt.stem.replace("=", "") + ".onnx")
    if not onnx.exists():
        subprocess.run(
            [sys.executable, "-m", "piper.train.export_onnx", "--checkpoint", str(ckpt), "--output-file", str(onnx)],
            check=True,
        )
    shutil.copyfile(config, str(onnx) + ".json")
    return onnx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True, help=".onnx voice or .ckpt checkpoint")
    ap.add_argument("--config", type=Path, default=None, help="voice config json; required for .ckpt")
    ap.add_argument("--text", action="append", default=[])
    ap.add_argument("--text-file", type=Path, default=None)
    ap.add_argument("--lexicon", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    model = args.model
    if model.suffix == ".ckpt":
        if not args.config:
            sys.exit("--config is required with a .ckpt model")
        model = export_checkpoint(model, args.config)

    texts = list(args.text)
    if args.text_file:
        for line in args.text_file.read_text(encoding="utf-8").splitlines():
            line = line.split("|", 1)[-1].strip()
            if line:
                texts.append(line)
    if not texts:
        sys.exit("No text given.")

    lexicon = load_lexicon(args.lexicon) if args.lexicon else None
    voice = PiperVoice.load(str(model))
    args.out.mkdir(parents=True, exist_ok=True)

    audio_seconds, started = 0.0, time.perf_counter()
    with open(args.out / "index.tsv", "w", encoding="utf-8", newline="\n") as index:
        for i, text in enumerate(texts, start=1):
            text = normalize(text, lexicon)
            name = f"{i:04d}.wav"
            with wave.open(str(args.out / name), "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
            with wave.open(str(args.out / name), "rb") as wav_file:
                audio_seconds += wav_file.getnframes() / wav_file.getframerate()
            index.write(f"{name}\t{text}\n")
    elapsed = time.perf_counter() - started

    print(f"{len(texts)} files, {audio_seconds:.1f} s audio in {elapsed:.1f} s")
    print(f"real-time factor {elapsed / audio_seconds:.3f} (below 1 is faster than real time)")


if __name__ == "__main__":
    main()
