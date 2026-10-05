"""Clean audio and text from download_data.py output into a Piper training set.

    python scripts/prepare_dataset.py --raw data/raw_s2 --out data/s2

Writes:
    <out>/wavs/*.wav            mono, 22050 Hz, 16-bit, trimmed, loudness-normalised
    <out>/metadata.csv          file.wav|normalised text   (training)
    <out>/metadata_smoke.csv    first 200 training lines   (smoke run)
    <out>/test.csv              held-out utterances, never trained on
    <out>/rejected.tsv          file, reason
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from functools import partial
from multiprocessing import Pool
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm
import soundfile as sf
from tqdm import tqdm

from normalize_ur import has_latin, load_lexicon, normalize

SAMPLE_RATE = 22050


def process(item, args, lexicon):
    """Returns (file, text, seconds, reject_reason)."""
    name, raw_text = item
    text = normalize(raw_text, lexicon)
    if not text:
        return name, text, 0.0, "empty_text"
    if has_latin(text):
        return name, text, 0.0, "latin_chars"

    samples, sr = sf.read(args.raw / "wavs" / name, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if np.mean(np.abs(samples) >= 0.999) > 0.001:
        return name, text, 0.0, "clipped"
    if sr != SAMPLE_RATE:
        samples = librosa.resample(samples, orig_sr=sr, target_sr=SAMPLE_RATE, res_type="soxr_hq")

    _, (start, end) = librosa.effects.trim(samples, top_db=args.trim_db)
    pad = int(args.pad_ms / 1000 * SAMPLE_RATE)
    samples = samples[max(0, start - pad) : min(len(samples), end + pad)]

    seconds = len(samples) / SAMPLE_RATE
    if seconds < args.min_sec:
        return name, text, seconds, "too_short"
    if seconds > args.max_sec:
        return name, text, seconds, "too_long"
    rate = len(text) / seconds
    if not args.min_cps <= rate <= args.max_cps:
        return name, text, seconds, f"chars_per_sec_{rate:.1f}"

    loudness = pyloudnorm.Meter(SAMPLE_RATE).integrated_loudness(samples)
    if np.isfinite(loudness):
        samples = samples * 10 ** ((args.lufs - loudness) / 20)
    peak = np.max(np.abs(samples))
    limit = 10 ** (-1 / 20)  # -1 dBFS
    if peak > limit:
        samples = samples * (limit / peak)

    sf.write(args.out / "wavs" / name, samples, SAMPLE_RATE, subtype="PCM_16")
    return name, text, seconds, None


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for name, text in rows:
            f.write(f"{name}|{text.replace('|', ' ')}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lexicon", type=Path, default=None)
    ap.add_argument("--min-sec", type=float, default=1.5)
    ap.add_argument("--max-sec", type=float, default=15.0)
    ap.add_argument("--min-cps", type=float, default=4.0, help="min characters per second")
    ap.add_argument("--max-cps", type=float, default=25.0)
    ap.add_argument("--trim-db", type=float, default=35.0)
    ap.add_argument("--pad-ms", type=float, default=150.0)
    ap.add_argument("--lufs", type=float, default=-23.0)
    ap.add_argument("--test-size", type=int, default=100)
    ap.add_argument("--smoke-size", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    lexicon = load_lexicon(args.lexicon) if args.lexicon else None
    items = []
    for line in (args.raw / "raw.tsv").read_text(encoding="utf-8").splitlines():
        name, _, text = line.partition("\t")
        items.append((name, text))
    (args.out / "wavs").mkdir(parents=True, exist_ok=True)

    kept, rejected, reasons, total_seconds = [], [], Counter(), 0.0
    with Pool(args.workers) as pool:
        results = pool.imap(partial(process, args=args, lexicon=lexicon), items, chunksize=32)
        for name, text, seconds, reason in tqdm(results, total=len(items), desc="processing"):
            if reason:
                rejected.append((name, reason))
                reasons[reason.split("_per_sec")[0]] += 1
            else:
                kept.append((name, text))
                total_seconds += seconds

    random.Random(args.seed).shuffle(kept)
    test, train = kept[: args.test_size], sorted(kept[args.test_size :])
    write_csv(args.out / "metadata.csv", train)
    write_csv(args.out / "metadata_smoke.csv", train[: args.smoke_size])
    write_csv(args.out / "test.csv", sorted(test))
    with open(args.out / "rejected.tsv", "w", encoding="utf-8", newline="\n") as f:
        for name, reason in rejected:
            f.write(f"{name}\t{reason}\n")

    print(f"kept {len(kept)} of {len(items)} clips, {total_seconds / 3600:.2f} h")
    print(f"train {len(train)}, test {len(test)}, rejected {len(rejected)}: {dict(reasons)}")


if __name__ == "__main__":
    main()
