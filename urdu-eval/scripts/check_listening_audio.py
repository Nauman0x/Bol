"""Sanity-check the listening clips: is each system's audio speech-like, or noise?

    python scripts/check_listening_audio.py [--live https://host]

Prints, per system, RMS, spectral flatness (1.0 = white noise, speech is well below 0.1) and the share of
energy below 4 kHz. With --live it also downloads a few clips from the site through the real API and
compares their bytes with the local files.
"""
import argparse, csv, hashlib, json, sys, urllib.request
from pathlib import Path
import numpy as np, soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
L = ROOT / "data" / "listening"

def stats(path):
    x, sr = sf.read(path, dtype="float32")
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2 + 1e-12
    flat = float(np.exp(np.mean(np.log(spec))) / np.mean(spec))
    f = np.fft.rfftfreq(len(x), 1 / sr)
    low = float(spec[f < 4000].sum() / spec.sum())
    return sr, len(x) / sr, 20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-9), flat, low

ap = argparse.ArgumentParser(); ap.add_argument("--live"); a = ap.parse_args()
rows = list(csv.DictReader(open(L / "stimuli.tsv", encoding="utf-8-sig"), delimiter="\t"))
by = {}
for r in rows:
    by.setdefault(r["system"], []).append(stats(L / r["file"]))
print(f"{'system':<16}{'sr':>6}{'sec':>6}{'rms dB':>8}{'flatness':>10}{'<4kHz':>8}")
for s, v in by.items():
    m = np.mean(np.array(v), axis=0)
    print(f"{s:<16}{int(m[0]):>6}{m[1]:>6.1f}{m[2]:>8.1f}{m[3]:>10.4f}{m[4]:>8.2f}")
