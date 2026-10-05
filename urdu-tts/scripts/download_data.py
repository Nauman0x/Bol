"""Download URDUTTS from Hugging Face and write one speaker's clips as WAV files.

    python scripts/download_data.py --inspect                 # show columns, speakers, sizes
    python scripts/download_data.py --speaker 2 --limit 20 --out data/listen_s2
    python scripts/download_data.py --speaker 2 --out data/raw_s2

Output: <out>/wavs/000001.wav ... and <out>/raw.tsv (file<TAB>text).

The dataset's column names were not known when this was written, so they are
detected from a list of likely names. Run --inspect first; if detection picks
the wrong column, pass --text-col / --speaker-col.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections import Counter
from pathlib import Path

import soundfile as sf
from datasets import Audio, concatenate_datasets, get_dataset_config_names, load_dataset
from tqdm import tqdm

TEXT_CANDIDATES = ["urdu", "urdu_text", "text", "transcription", "transcript", "sentence", "normalized_text"]
SPEAKER_CANDIDATES = ["speaker", "speaker_id", "speaker_name", "spk", "spk_id"]
DURATION_CANDIDATES = ["duration", "duration_s", "duration_sec", "length"]


def pick(columns, candidates, override, what, required=True):
    if override:
        if override not in columns:
            sys.exit(f"--{what}-col {override!r} not in columns {columns}")
        return override
    for name in candidates:
        if name in columns:
            return name
    if required:
        sys.exit(f"Could not find the {what} column in {columns}. Pass --{what}-col.")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="XKaab/URDUTTS")
    ap.add_argument("--config", default=None)
    ap.add_argument("--split", default=None, help="default: all splits concatenated")
    ap.add_argument("--speaker", default=None, help="value in the speaker column, or 'all'")
    ap.add_argument("--text-col", default=None)
    ap.add_argument("--speaker-col", default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None, help="write only the first N clips")
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    print("configs:", get_dataset_config_names(args.repo))
    loaded = load_dataset(args.repo, name=args.config, split=args.split)
    if args.split is None:
        print("splits:", {name: len(part) for name, part in loaded.items()})
        ds = concatenate_datasets(list(loaded.values()))
    else:
        ds = loaded
    print("features:", ds.features)

    audio_cols = [name for name, feat in ds.features.items() if isinstance(feat, Audio)]
    if len(audio_cols) != 1:
        sys.exit(f"Expected exactly one audio column, found {audio_cols}")
    audio_col = audio_cols[0]
    # Keep audio as raw bytes: avoids the datasets audio-decoder dependency and
    # makes column access (speaker counts, filtering) cheap.
    ds = ds.cast_column(audio_col, Audio(decode=False))

    columns = ds.column_names
    text_col = pick(columns, TEXT_CANDIDATES, args.text_col, "text")
    speaker_col = pick(columns, SPEAKER_CANDIDATES, args.speaker_col, "speaker", required=False)
    duration_col = pick(columns, DURATION_CANDIDATES, None, "duration", required=False)
    print(f"audio={audio_col!r} text={text_col!r} speaker={speaker_col!r} duration={duration_col!r}")

    if speaker_col:
        speakers = ds[speaker_col]
        clips = Counter(str(s) for s in speakers)
        hours = Counter()
        if duration_col:
            for s, d in zip(speakers, ds[duration_col]):
                hours[str(s)] += float(d) / 3600
        print("speakers:")
        for name, n in sorted(clips.items()):
            extra = f", {hours[name]:.2f} h" if duration_col else ""
            print(f"  {name!r}: {n} clips{extra}")

    if args.inspect:
        row = ds[0]
        row[audio_col] = {"path": row[audio_col].get("path"), "bytes": "<omitted>"}
        print("first row:", row)
        return

    if not args.out or not args.speaker:
        sys.exit("Pass --speaker and --out (or --inspect).")

    if args.speaker != "all":
        if not speaker_col:
            sys.exit("No speaker column found; use --speaker all or pass --speaker-col.")
        if args.speaker not in clips:
            sys.exit(f"Speaker {args.speaker!r} not found. Available: {sorted(clips)}")
        ds = ds.filter(lambda s: str(s) == args.speaker, input_columns=[speaker_col])
    if args.limit:
        ds = ds.select(range(min(args.limit, len(ds))))

    wav_dir = args.out / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    total_seconds = 0.0
    with open(args.out / "raw.tsv", "w", encoding="utf-8", newline="\n") as tsv:
        for i, row in enumerate(tqdm(ds, desc="writing wavs"), start=1):
            audio = row[audio_col]
            source = io.BytesIO(audio["bytes"]) if audio.get("bytes") else audio["path"]
            samples, sr = sf.read(source, dtype="float32", always_2d=False)
            name = f"{i:06d}.wav"
            sf.write(wav_dir / name, samples, sr, subtype="PCM_16")
            total_seconds += len(samples) / sr
            text = " ".join(str(row[text_col]).split())
            tsv.write(f"{name}\t{text}\n")

    print(f"Wrote {len(ds)} clips, {total_seconds / 3600:.2f} h, to {args.out}")


if __name__ == "__main__":
    main()
