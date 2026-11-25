"""Synthesise Esha's held-out sentences with each TTS system and build per-system manifests.

    python scripts/synth_esha.py [--ckpt <path to esha .ckpt>]

Esha's 80 held-out sentences (urdu-tts/data/esha/test.csv) were never in training, and her real recordings of
them (urdu-tts/evalrun/REAL_esha) are the same-speaker human reference. Systems:

  esha_real         Esha's real recording (human reference)
  esha_voice        our Piper voice trained on Esha (final checkpoint unless --ckpt is given)
  bol_rasa_female   our earlier voice, trained on Indian-Urdu Rasa speech (the starting point for the Esha voice)
  stock_fasih       stock Piper Urdu voice (baseline)

Writes data/esha/<system>/<id>.wav and data/esha_manifest_<system>.tsv (columns as manifest.tsv).
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TTS = Path.home() / "urdu-tts"
ESHA_TEST = TTS / "data" / "esha" / "test.csv"
ESHA_WAVS = TTS / "data" / "esha" / "wavs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", type=Path, default=TTS / "runs_esha/lightning_logs/version_2/checkpoints/last.ckpt")
    args = ap.parse_args()

    items = []  # (id, text)
    for line in ESHA_TEST.read_text(encoding="utf-8").splitlines():
        name, _, text = line.partition("|")
        if text.strip():
            items.append((Path(name).stem, text.strip()))
    out_root = DATA / "esha"
    out_root.mkdir(exist_ok=True)

    # Esha's real recordings of the held-out sentences
    real = out_root / "esha_real"
    real.mkdir(exist_ok=True)
    for sid, _ in items:
        shutil.copyfile(ESHA_WAVS / f"{sid}.wav", real / f"{sid}.wav")

    systems = {
        "esha_voice": [str(args.ckpt), "--config", str(TTS / "runs_esha/ur_PK-bol_esha-medium.onnx.json")],
        "bol_rasa_female": [str(TTS / "export/ur_PK-bol_rasa_female-medium.onnx")],
        "stock_fasih": [str(TTS / "voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx")],
    }
    text_file = DATA / "esha_input.txt"
    text_file.write_text("\n".join(t for _, t in items) + "\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(TTS / "scripts")}
    for name, model_args in systems.items():
        out = out_root / name
        tmp = out_root / f"_{name}_tmp"  # synth.py names files 0001.wav..., which collide with Esha's own ids
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        p = subprocess.run(
            [sys.executable, str(TTS / "scripts/synth.py"), "--model", model_args[0], *model_args[1:],
             "--text-file", str(text_file), "--out", str(tmp)],
            cwd=TTS, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        if p.returncode:
            sys.exit(f"{name} failed:\n{p.stderr[-2000:]}")
        print(name, "|", p.stdout.strip().replace("\n", " | "))
        for i, (sid, _) in enumerate(items, start=1):
            (tmp / f"{i:04d}.wav").replace(out / f"{sid}.wav")
        shutil.rmtree(tmp)

    cols = ["speaker_id", "sentence_id", "group", "wav", "flags", "ref"]
    for name in ["esha_real", *systems]:
        with open(DATA / f"esha_manifest_{name}.tsv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
            w.writeheader()
            for sid, text in items:
                w.writerow({"speaker_id": name, "sentence_id": sid, "group": "esha_test",
                            "wav": f"esha/{name}/{sid}.wav", "flags": "", "ref": text})
    print(f"{len(items)} sentences x {1 + len(systems)} systems")


if __name__ == "__main__":
    main()
