"""Download one speaker of ASLP-lab/UrduSpeech (casual, code-switched Pakistani Urdu).

    python scripts/download_aslp.py --category podcast --speaker SPEAKER_0038 --out data/raw_p38

UrduSpeech (CC BY 4.0) is podcasts, interviews, vlogs etc. from YouTube and PTV,
diarized into speakers per content category. Its transcripts mix Urdu script with
English words in Latin script; prepare with --allow-latin to keep those.

Speaker ids come from automatic diarization, so a few clips can belong to someone
else (a host, a guest, crosstalk). Each clip is compared with the speaker's
typical voice (WavLM x-vector) and clips below --min-sim are left out; the
similarity of every clip is written to <out>/speaker_check.tsv.

Output: <out>/wavs/*.wav and <out>/raw.tsv (file<TAB>text), as download_data.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import HfApi, hf_hub_download
from tqdm import tqdm

from download_data import Embedder

REPO = "ASLP-lab/UrduSpeech"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="US-CS", help="US-CS (code-switched), US-Std or US-EngPk")
    ap.add_argument("--category", required=True, help="e.g. podcast, interview, vlogs, roadside_interview")
    ap.add_argument("--speaker", required=True, help="e.g. SPEAKER_0038")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-sim", type=float, default=0.85, help="cosine similarity to the speaker's median voice")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    files = set(HfApi().list_repo_files(REPO, repo_type="dataset"))
    clips = {}
    for fmt in ("short", "long"):
        meta = f"corpus/{args.subset}/{fmt}/{args.category}/{args.category}_final_transcription.jsonl"
        if meta not in files:
            continue
        for line in open(hf_hub_download(REPO, meta, repo_type="dataset"), encoding="utf-8"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            audio = f"corpus/{args.subset}/{fmt}/{args.category}/audio/{row.get('Audio_Clip')}"
            if row.get("Speaker_id") == args.speaker and audio in files and row.get("Transcription"):
                clips[audio] = " ".join(str(row["Transcription"]).split())
    if not clips:
        sys.exit(f"No clips for {args.speaker} in {args.subset}/{args.category}.")
    print(f"{len(clips)} clips listed for {args.speaker}")

    wav_dir = args.out / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    names, audio = [], []
    for path in tqdm(sorted(clips), desc="download"):
        name = path.rsplit("/", 1)[-1]
        # copyfile, not copy: the hub cache files are read-only.
        shutil.copyfile(hf_hub_download(REPO, path, repo_type="dataset"), wav_dir / name)
        samples, sr = sf.read(wav_dir / name, dtype="float32", always_2d=True)
        names.append(name)
        audio.append((samples.mean(axis=1), sr))

    embs = Embedder("cuda" if torch.cuda.is_available() else "cpu")(audio)
    typical = np.median(embs, axis=0)
    sims = embs @ (typical / np.linalg.norm(typical))
    keep = sims >= args.min_sim
    print("similarity percentiles 1/5/25/50:", np.round(np.percentile(sims, [1, 5, 25, 50]), 3))

    texts = [clips[p] for p in sorted(clips)]
    with open(args.out / "speaker_check.tsv", "w", encoding="utf-8", newline="\n") as check:
        for name, sim, kept in sorted(zip(names, sims, keep), key=lambda x: x[1]):
            check.write(f"{name}\t{sim:.3f}\t{'kept' if kept else 'dropped'}\n")
    seconds = 0.0
    with open(args.out / "raw.tsv", "w", encoding="utf-8", newline="\n") as tsv:
        for name, (samples, sr), text, kept in zip(names, audio, texts, keep):
            if kept:
                tsv.write(f"{name}\t{text}\n")
                seconds += len(samples) / sr
            else:
                (wav_dir / name).unlink()
    print(f"kept {keep.sum()} of {len(names)} clips ({seconds / 3600:.2f} h); "
          f"dropped {(~keep).sum()} below similarity {args.min_sim} (see speaker_check.tsv)")


if __name__ == "__main__":
    main()
