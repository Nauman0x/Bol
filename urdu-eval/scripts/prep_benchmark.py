"""Convert the exported classmate recordings to 16 kHz mono WAV and run quality checks.

    python scripts/prep_benchmark.py            # reads data/metadata.csv + data/sentences.tsv

Writes data/wav/<speaker>_<sentence>.wav and data/manifest.tsv (one row per clip, with the
reference text and QC numbers). A clip is flagged, not deleted, when it looks wrong, so the
decision to drop it is made by a person.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


# Recordings made before the recorder fixed its right-to-left digit display (2026-11-25): the speaker read
# digits in the order the browser showed them, not the order of the reference text. Not scorable against ref.
INVALID_STIMULUS = {"c96c5c98": {"n01", "n02", "n04", "n05", "n06"}}


def load_sentences() -> dict[str, dict]:
    out = {}
    with open(DATA / "sentences.tsv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            out[r["id"]] = r
    return out


def to_wav(src: Path, dst: Path) -> None:
    dst.parent.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
        check=True,
    )


def qc(path: Path) -> dict:
    x, sr = sf.read(path, dtype="float32")
    secs = len(x) / sr
    peak = float(np.abs(x).max()) if len(x) else 0.0
    rms = float(np.sqrt(np.mean(x**2))) if len(x) else 0.0
    # frame energy (20 ms) to find leading/trailing silence and the active-speech share
    n = int(0.02 * sr)
    frames = x[: len(x) // n * n].reshape(-1, n)
    e = np.sqrt((frames**2).mean(axis=1))
    thr = max(0.005, 0.1 * float(np.percentile(e, 95)))
    active = e > thr
    idx = np.flatnonzero(active)
    lead = idx[0] * 0.02 if len(idx) else secs
    trail = (len(e) - 1 - idx[-1]) * 0.02 if len(idx) else secs
    return {
        "seconds": round(secs, 2),
        "peak_dbfs": round(20 * np.log10(peak + 1e-9), 1),
        "rms_dbfs": round(20 * np.log10(rms + 1e-9), 1),
        "clipped_pct": round(float((np.abs(x) > 0.999).mean() * 100), 3),
        "lead_s": round(float(lead), 2),
        "trail_s": round(float(trail), 2),
        "active_pct": round(float(active.mean() * 100), 1),
    }


def main() -> None:
    sent = load_sentences()
    rows = []
    with open(DATA / "metadata.csv", encoding="utf-8-sig", newline="") as f:
        meta = list(csv.DictReader(f))
    for m in meta:
        sid = m["sentence_id"]
        src = DATA / m["raw_file"]
        dst = DATA / "wav" / f"{m['speaker_id']}_{sid}.wav"
        if not dst.exists():
            to_wav(src, dst)
        q = qc(dst)
        s = sent[sid]
        flags = []
        if q["peak_dbfs"] < -30:
            flags.append("very_quiet")
        if q["clipped_pct"] > 0.1:
            flags.append("clipped")
        if q["active_pct"] < 25:
            flags.append("mostly_silence")
        if q["lead_s"] > 2.0 or q["trail_s"] > 2.5:
            flags.append("long_silence_edge")
        if s["group"] != "free" and q["seconds"] < 1.0:
            flags.append("too_short")
        if sid in INVALID_STIMULUS.get(m["speaker_id"], ()):
            flags.append("invalid_stimulus")
        rows.append({
            "speaker_id": m["speaker_id"], "sentence_id": sid, "group": s["group"],
            "gender": m["gender"], "region": m["region"], "device": m["device"], "environment": m["environment"],
            "wav": str(dst.relative_to(DATA)), **q, "flags": ",".join(flags),
            "text": s["text"], "ref": s["ref"],
        })
    out = DATA / "manifest.tsv"
    cols = list(rows[0])
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    tot = sum(r["seconds"] for r in rows)
    flagged = [r for r in rows if r["flags"]]
    print(f"{len(rows)} clips, {len({r['speaker_id'] for r in rows})} speakers, {tot / 60:.1f} min total")
    print(f"loudness (rms dBFS): median {np.median([r['rms_dbfs'] for r in rows]):.1f}, "
          f"range {min(r['rms_dbfs'] for r in rows):.1f}..{max(r['rms_dbfs'] for r in rows):.1f}")
    print(f"flagged clips: {len(flagged)}")
    for r in flagged:
        print(f"  {r['speaker_id']}_{r['sentence_id']}: {r['flags']} ({r['seconds']}s, peak {r['peak_dbfs']} dBFS)")
    print("wrote", out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
