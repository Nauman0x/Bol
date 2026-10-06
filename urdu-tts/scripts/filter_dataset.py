"""Drop training clips whose transcript does not match the audio.

    python scripts/eval_cer.py data/p38 --index data/p38/metadata.csv --save data/p38/cer_train.tsv
    python scripts/filter_dataset.py --data data/p38 --cer data/p38/cer_train.tsv --out data/p38c

ASLP's transcripts are machine-made, and some include words spoken before or
after the clip. Training on them teaches the model to mumble. A clip is dropped
when Whisper's transcript of its audio is too far from its text: mostly-Urdu
clips are judged strictly (--max-cer-urdu), English-heavy ones loosely
(--max-cer), because Whisper writes English in Urdu script or drops it, which
inflates their CER even when the transcript is right.

<out> gets metadata.csv, metadata_smoke.csv and the unchanged test.csv; wavs/
links to <data>/wavs. Train with DATA=<out>.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--cer", type=Path, required=True, help="eval_cer.py --save output for <data>/metadata.csv")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-cer", type=float, default=0.8)
    ap.add_argument("--max-cer-urdu", type=float, default=0.5)
    ap.add_argument("--urdu-below", type=float, default=0.3, help="latin share under which a clip counts as mostly Urdu")
    ap.add_argument("--smoke-size", type=int, default=200)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.cer, encoding="utf-8", newline="") as f:
        scores = {r["file"]: r for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)}

    kept, dropped = [], []
    for line in (args.data / "metadata.csv").read_text(encoding="utf-8").splitlines():
        name = line.partition("|")[0]
        r = scores.get(name)
        if r is None:
            sys.exit(f"{name} is not in {args.cer}; run eval_cer.py on {args.data}/metadata.csv first")
        cer, latin = float(r["cer"]), float(r["latin"])
        limit = args.max_cer_urdu if latin < args.urdu_below else args.max_cer
        (kept if cer <= limit else dropped).append(line)

    args.out.mkdir(parents=True, exist_ok=True)
    wavs = args.out / "wavs"
    if not wavs.exists():
        os.symlink(os.path.relpath(args.data / "wavs", args.out), wavs)
    (args.out / "metadata.csv").write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    (args.out / "metadata_smoke.csv").write_text("".join(l + "\n" for l in kept[: args.smoke_size]), encoding="utf-8")
    (args.out / "test.csv").write_text((args.data / "test.csv").read_text(encoding="utf-8"), encoding="utf-8")
    (args.out / "dropped.csv").write_text("".join(l + "\n" for l in dropped), encoding="utf-8")
    print(f"kept {len(kept)}, dropped {len(dropped)} (see {args.out / 'dropped.csv'})")


if __name__ == "__main__":
    main()
