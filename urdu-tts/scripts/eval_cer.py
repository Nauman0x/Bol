"""Round-trip intelligibility check: transcribe audio with Whisper and compare with
the text it should contain.

    python scripts/eval_cer.py samples/test                    # synth.py output (wavs + index.tsv)
    python scripts/eval_cer.py data/p38 --index data/p38/metadata.csv --save data/p38/cer.tsv

Lower character error rate (CER) is better. Whisper makes its own mistakes on
Urdu, so compare numbers between voices (stock baseline vs ours) rather than
reading them as absolute. It also writes English words in Urdu script or drops
them, so code-switched clips score higher; the saved `latin` column shows how
much of each text is English.

With --index (a Piper csv, file|text, audio under <dir>/wavs/) it checks a
training set instead: a clip whose transcript does not match its audio scores
far worse than the rest. --save writes per-clip results, worst first, for
filter_dataset.py.

Whisper sometimes loops on one phrase ("مجھے مجھے مجھے ..."), which would put a
single clip at 1000%+ CER and swamp any average. So repeats are suppressed, the
hypothesis is cut at 1.5x the reference length, each clip's CER is capped at
100%, and the median is reported alongside the mean.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

import jiwer
import soundfile as sf
import soxr
import torch
from transformers import pipeline

from normalize_ur import PUNCT, normalize

_STRIP = re.compile(rf"[ً-ْٰ{PUNCT}]")
_LATIN = re.compile(r"[A-Za-z]")


def comparable(text: str) -> str:
    return " ".join(_STRIP.sub(" ", normalize(text)).split())


def latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(bool(_LATIN.match(c)) for c in letters) / max(1, len(letters))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", type=Path)
    ap.add_argument("--model", default="openai/whisper-large-v3-turbo")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--worst", type=int, default=5)
    ap.add_argument("--index", type=Path, default=None, help="file|text csv; audio in <samples>/wavs/")
    ap.add_argument("--save", type=Path, default=None, help="write file, cer, seconds, latin, ref, hyp (TSV, worst first)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    asr = pipeline(
        "automatic-speech-recognition",
        model=args.model,
        device=args.device,
        dtype=torch.float16 if args.device.startswith("cuda") else torch.float32,
    )

    if args.index:
        audio_dir, sep, index = args.samples / "wavs", "|", args.index
    else:
        audio_dir, sep, index = args.samples, "\t", args.samples / "index.tsv"

    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        name, _, text = line.partition(sep)
        samples, sr = sf.read(audio_dir / name, dtype="float32")
        seconds = len(samples) / sr
        # Resample here: the pipeline would need torchaudio, which has no build for this torch.
        samples = soxr.resample(samples, sr, 16000)
        result = asr(
            {"raw": samples, "sampling_rate": 16000},
            return_timestamps=seconds > 29,  # Whisper needs long-form mode past 30 s
            generate_kwargs={"language": "urdu", "task": "transcribe", "no_repeat_ngram_size": 4},
        )
        ref = comparable(text)
        hyp = comparable(result["text"])[: int(len(ref) * 1.5) + 10]
        rows.append((min(1.0, jiwer.cer(ref, hyp)), name, seconds, latin_share(text), ref, hyp))

    cers = [r[0] for r in rows]
    print(f"{len(rows)} utterances, CER median {statistics.median(cers):.1%}, mean {statistics.mean(cers):.1%}, "
          f"over 60%: {sum(c > 0.6 for c in cers)}")
    if args.save:
        with open(args.save, "w", encoding="utf-8", newline="\n") as f:
            f.write("file\tcer\tseconds\tlatin\tref\thyp\n")
            for cer, name, seconds, latin, ref, hyp in sorted(rows, reverse=True):
                f.write(f"{name}\t{cer:.3f}\t{seconds:.1f}\t{latin:.2f}\t{ref}\t{hyp}\n")
    if args.worst:
        print(f"\nworst {args.worst}:")
        for cer, name, _, _, ref, hyp in sorted(rows, reverse=True)[: args.worst]:
            print(f"{name}  CER {cer:.0%}\n  ref: {ref}\n  hyp: {hyp}")


if __name__ == "__main__":
    main()
