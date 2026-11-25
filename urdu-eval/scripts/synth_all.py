"""Synthesise every scripted benchmark sentence with each TTS system and write a manifest per system.

    python scripts/synth_all.py                       # run with the piper venv python, from anywhere

Input text is the spoken form (`ref` column: digit strings already written out digit by digit), so the
voices read the same words the human speaker was asked to say. All systems go through the same text
pipeline (urdu-tts/scripts/synth.py: normaliser + lexicons). Output: data/tts/<system>/<sentence>.wav and
data/tts_manifest_<system>.tsv (same columns as manifest.tsv, so eval_asr.py can score it with --manifest).
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TTS_DIR = Path.home() / "urdu-tts"

SYSTEMS = {
    "stock_fasih": TTS_DIR / "voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx",
    "bol_rasa_male": TTS_DIR / "export/ur_PK-bol_rasa_male-medium.onnx",
    "bol_rasa_female": TTS_DIR / "export/ur_PK-bol_rasa_female-medium.onnx",
}


def main() -> None:
    with open(DATA / "manifest.tsv", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if r["ref"]]
    texts = [r["ref"] for r in rows]
    text_file = DATA / "tts_input.txt"
    text_file.write_text("\n".join(texts) + "\n", encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(TTS_DIR / "scripts")}
    for name, model in SYSTEMS.items():
        out = DATA / "tts" / name
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        p = subprocess.run(
            [sys.executable, str(TTS_DIR / "scripts" / "synth.py"), "--model", str(model),
             "--text-file", str(text_file), "--out", str(out)],
            cwd=TTS_DIR, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        if p.returncode:
            sys.exit(p.stderr[-2000:])
        print(name, "|", p.stdout.strip().replace("\n", " | "), f"| wall {time.perf_counter() - t0:.0f}s")
        # rename 0001.wav... to <sentence>.wav, in the same order the text file was written
        for i, r in enumerate(rows, start=1):
            src = out / f"{i:04d}.wav"
            src.replace(out / f"{r['sentence_id']}.wav")
        cols = list(rows[0])
        with open(DATA / f"tts_manifest_{name}.tsv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
            w.writeheader()
            for r in rows:
                w.writerow({**r, "speaker_id": name, "wav": f"tts/{name}/{r['sentence_id']}.wav", "flags": ""})


if __name__ == "__main__":
    main()
