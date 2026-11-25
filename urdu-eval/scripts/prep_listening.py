"""Build the blind listening-test stimuli.

    python scripts/prep_listening.py

For every benchmark sentence where the human recording is valid, writes four systems plus a low anchor to
data/listening/<system>/<sentence>.wav (22.05 kHz mono 16-bit) and data/listening/stimuli.tsv:

  human            the classmate recording (re-decoded from the original file, not the 16 kHz scoring copy)
  stock_fasih      stock Piper Urdu voice
  bol_rasa_male    our fine-tuned male voice
  bol_rasa_female  our fine-tuned female voice
  anchor           the human clip deliberately degraded (3 kHz bandwidth, noise, 6-bit); raters should score it low

All clips get the same treatment so loudness and silence cannot give the system away: leading/trailing
silence trimmed to 150 ms, RMS set to -23 dBFS (peak-limited to -1 dBFS).
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "listening"
SR = 22050
SYSTEMS = ["human", "stock_fasih", "bol_rasa_male", "bol_rasa_female"]


def decode(path: Path) -> np.ndarray:
    tmp = OUT / "_tmp.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), str(tmp)], check=True)
    x, _ = sf.read(tmp, dtype="float32")
    return x


def load(path: Path) -> np.ndarray:
    if path.suffix == ".webm":
        return decode(path)
    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    return soxr.resample(x, sr, SR) if sr != SR else x


def trim(x: np.ndarray, pad: float = 0.15) -> np.ndarray:
    n = int(0.02 * SR)
    frames = x[: len(x) // n * n].reshape(-1, n)
    e = np.sqrt((frames**2).mean(axis=1))
    thr = max(0.003, 0.08 * float(np.percentile(e, 95)))
    idx = np.flatnonzero(e > thr)
    if not len(idx):
        return x
    a = max(0, idx[0] * n - int(pad * SR))
    b = min(len(x), (idx[-1] + 1) * n + int(pad * SR))
    return x[a:b]


def level(x: np.ndarray, rms_db: float = -23.0, peak_db: float = -1.0) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x**2))) + 1e-9
    g = min(10 ** ((rms_db - 20 * np.log10(rms)) / 20), 10 ** (peak_db / 20) / (float(np.abs(x).max()) + 1e-9))
    return x * g


def degrade(x: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y = soxr.resample(soxr.resample(x, SR, 3000), 3000, SR)[: len(x)]
    y = np.pad(y, (0, len(x) - len(y)))
    y = y + rng.normal(0, float(np.sqrt(np.mean(y**2))) * 0.35, size=len(y)).astype(np.float32)
    return np.round(np.clip(y, -1, 1) * 31) / 31


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with open(DATA / "manifest.tsv", encoding="utf-8-sig", newline="") as f:
        valid = [r for r in csv.DictReader(f, delimiter="\t") if r["ref"] and "invalid_stimulus" not in r["flags"]]
    rows = []
    for r in valid:
        sid = r["sentence_id"]
        raw = DATA / "raw" / f"{r['speaker_id']}_{sid}.webm"
        clips = {"human": load(raw)}
        for s in SYSTEMS[1:]:
            clips[s] = load(DATA / "tts" / s / f"{sid}.wav")
        clips["anchor"] = degrade(clips["human"], seed=int(sum(map(ord, sid))))
        for system, x in clips.items():
            y = level(trim(x))
            d = OUT / system
            d.mkdir(exist_ok=True)
            sf.write(d / f"{sid}.wav", y, SR, subtype="PCM_16")
            rows.append({"sentence_id": sid, "group": r["group"], "system": system,
                         "file": f"{system}/{sid}.wav", "seconds": round(len(y) / SR, 2)})
    (OUT / "_tmp.wav").unlink(missing_ok=True)
    with open(OUT / "stimuli.tsv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    mb = sum((OUT / r["file"]).stat().st_size for r in rows) / 1e6
    print(f"{len(valid)} sentences x {len(clips)} systems = {len(rows)} clips, {mb:.1f} MB")
    for s in clips:
        secs = [r["seconds"] for r in rows if r["system"] == s]
        print(f"  {s:<16} mean {np.mean(secs):.1f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
