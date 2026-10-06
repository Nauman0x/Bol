"""Download one speaker of the Urdu part of ai4bharat/Rasa (studio-recorded, CC BY 4.0).

    python scripts/download_rasa.py --inspect                      # hours per gender and style
    python scripts/download_rasa.py --listen data/rasa_listen      # 5 clips per gender and style
    python scripts/download_rasa.py --gender Male --exclude WIKI,BOOK,NEWS --out data/raw_rasa_m

Rasa has one male and one female voice per language (20+ h each) in several
speaking styles: neutral Wikipedia readings, book narration, news, commands for
assistants, the six Ekman emotions, and natural conversation. For a casual voice
keep the conversational, command and emotion styles and drop the formal reading
ones with --exclude (or name the ones to keep with --styles).

The dataset is gated: accept its terms on Hugging Face and run `hf auth login`.
Parquet is read by column, so --inspect fetches only the small text columns, and
audio is read only for row groups that contain a wanted clip. Resumable: rerun
the same command after an interruption.

Output: <out>/wavs/*.wav and <out>/raw.tsv (file<TAB>text), as download_data.py.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq
import soundfile as sf
from huggingface_hub import HfFileSystem
from tqdm import tqdm

REPO = "datasets/ai4bharat/Rasa"
META = ["filename", "text", "gender", "style", "duration"]


def shards(fs):
    files = fs.glob(f"{REPO}/Urdu/*.parquet")
    return sorted(files, key=lambda f: ("test" in f, f))  # train shards first


def row_groups(fs, path, columns):
    with fs.open(path, "rb", block_size=2**20) as f:
        pf = pq.ParquetFile(f)
        for i in range(pf.num_row_groups):
            yield i, pf.read_row_group(i, columns=columns).to_pylist()


def keep(row, args):
    style = str(row["style"]).upper()
    if args.gender and str(row["gender"]).lower() != args.gender.lower():
        return False
    if args.styles and not any(style.startswith(s) for s in args.styles):
        return False
    if args.exclude and any(style.startswith(s) for s in args.exclude):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--listen", type=Path, default=None, help="write a few clips per gender and style here")
    ap.add_argument("--per-style", type=int, default=5)
    ap.add_argument("--gender", default=None, help="Male or Female")
    ap.add_argument("--styles", default="", help="comma-separated style prefixes to keep, e.g. CONV,HAPPY")
    ap.add_argument("--exclude", default="", help="comma-separated style prefixes to drop, e.g. WIKI,BOOK,NEWS")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--hours", type=float, default=None, help="stop after this much audio")
    args = ap.parse_args()
    args.styles = [s.strip().upper() for s in args.styles.split(",") if s.strip()]
    args.exclude = [s.strip().upper() for s in args.exclude.split(",") if s.strip()]
    sys.stdout.reconfigure(encoding="utf-8")

    fs = HfFileSystem()
    files = shards(fs)
    print(f"{len(files)} Urdu shards")

    if args.inspect:
        hours, clips, example = defaultdict(float), defaultdict(int), {}
        for path in tqdm(files, desc="metadata"):
            for _, rows in row_groups(fs, path, META):
                for r in rows:
                    key = (r["gender"], r["style"])
                    hours[key] += float(r["duration"] or 0) / 3600
                    clips[key] += 1
                    example.setdefault(key, r["text"])
        for key in sorted(hours):
            print(f"{key[0]:7} {key[1]:12} {clips[key]:6} clips {hours[key]:6.2f} h   e.g. {example[key][:70]}")
        return

    if args.listen:
        taken = defaultdict(int)
        args.listen.mkdir(parents=True, exist_ok=True)
        index = open(args.listen / "index.tsv", "w", encoding="utf-8", newline="\n")
        for path in files:
            for i, rows in row_groups(fs, path, META):
                want = [j for j, r in enumerate(rows) if taken[(r["gender"], r["style"])] < args.per_style]
                if not want:
                    continue
                with fs.open(path, "rb", block_size=2**20) as f:
                    audio = pq.ParquetFile(f).read_row_group(i, columns=["audio"]).column("audio").to_pylist()
                for j in want:
                    r = rows[j]
                    key = (r["gender"], r["style"])
                    if taken[key] >= args.per_style:
                        continue
                    taken[key] += 1
                    name = f"{r['gender']}_{r['style']}_{taken[key]}.wav"
                    (args.listen / name).write_bytes(audio[j]["bytes"])
                    index.write(f"{name}\t{r['text']}\n")
            if taken and all(n >= args.per_style for n in taken.values()) and len(taken) >= 10:
                break
        print(f"wrote {sum(taken.values())} clips to {args.listen}")
        return

    if not args.out:
        sys.exit("Pass --inspect, --listen DIR, or --out DIR.")
    wav_dir = args.out / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.out / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"done": [], "count": 0, "seconds": 0.0}
    tsv_path = args.out / "raw.tsv"
    lines = tsv_path.read_text(encoding="utf-8").splitlines()[: state["count"]] if tsv_path.exists() else []
    tsv_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    for path in files:
        if args.hours and state["seconds"] >= args.hours * 3600:
            break
        if path in state["done"]:
            continue
        kept = 0
        with open(tsv_path, "a", encoding="utf-8", newline="\n") as tsv:
            for i, rows in row_groups(fs, path, META):
                want = [j for j, r in enumerate(rows) if keep(r, args)]
                if not want:
                    continue
                with fs.open(path, "rb", block_size=2**20) as f:
                    audio = pq.ParquetFile(f).read_row_group(i, columns=["audio"]).column("audio").to_pylist()
                for j in want:
                    samples, sr = sf.read(io.BytesIO(audio[j]["bytes"]), dtype="float32", always_2d=True)
                    name = Path(rows[j]["filename"]).stem + ".wav"
                    sf.write(wav_dir / name, samples.mean(axis=1), sr, subtype="PCM_16")
                    tsv.write(f"{name}\t{' '.join(str(rows[j]['text']).split())}\n")
                    state["count"] += 1
                    state["seconds"] += len(samples) / sr
                    kept += 1
        state["done"].append(path)
        state_file.write_text(json.dumps(state))
        print(f"{Path(path).name}: kept {kept}; total {state['count']} clips, {state['seconds'] / 3600:.2f} h", flush=True)

    print(f"{state['count']} clips, {state['seconds'] / 3600:.2f} h in {args.out}")


if __name__ == "__main__":
    main()
