"""Round-trip intelligibility check: transcribe synthesised audio with Whisper and
compare with the text it was synthesised from.

    python scripts/eval_cer.py samples/test

The directory is synth.py output (wavs + index.tsv). Lower character error rate
is better. Whisper makes its own mistakes on Urdu, so compare numbers between
voices (stock baseline vs ours) rather than reading them as absolute.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import jiwer
import soundfile as sf
import torch
from transformers import pipeline

from normalize_ur import PUNCT, normalize

_STRIP = re.compile(rf"[ً-ْٰ{PUNCT}]")


def comparable(text: str) -> str:
    return " ".join(_STRIP.sub(" ", normalize(text)).split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", type=Path)
    ap.add_argument("--model", default="openai/whisper-large-v3")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--worst", type=int, default=10)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    asr = pipeline(
        "automatic-speech-recognition",
        model=args.model,
        device=args.device,
        torch_dtype=torch.float16 if args.device.startswith("cuda") else torch.float32,
    )

    rows = []
    for line in (args.samples / "index.tsv").read_text(encoding="utf-8").splitlines():
        name, _, text = line.partition("\t")
        samples, sr = sf.read(args.samples / name, dtype="float32")
        result = asr(
            {"raw": samples, "sampling_rate": sr},
            generate_kwargs={"language": "urdu", "task": "transcribe"},
        )
        ref, hyp = comparable(text), comparable(result["text"])
        rows.append((jiwer.cer(ref, hyp), name, ref, hyp))

    overall = jiwer.cer([r[2] for r in rows], [r[3] for r in rows])
    print(f"{len(rows)} utterances, CER {overall:.2%}")
    print(f"\nworst {args.worst}:")
    for cer, name, ref, hyp in sorted(rows, reverse=True)[: args.worst]:
        print(f"{name}  CER {cer:.0%}\n  ref: {ref}\n  hyp: {hyp}")


if __name__ == "__main__":
    main()
