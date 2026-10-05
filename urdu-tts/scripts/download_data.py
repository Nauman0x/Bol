"""Download URDUTTS from Hugging Face and extract one speaker's clips as WAV files.

    python scripts/download_data.py --inspect                  # columns, splits, shard sizes
    python scripts/download_data.py --cluster --shards 2       # find the 4 voices, write samples
    python scripts/download_data.py --voice 2 --out data/raw_v2 --hours 15

The release (kaab4321/UrduTTS) has four male speakers but no speaker labels, so
--cluster groups clips by speaker embedding (WavLM x-vectors) into 4 voices,
saves the centroids to data/voices.npz, and writes the 20 most typical clips of
each voice to data/listen_v1 ... data/listen_v4 to listen to. --voice then
downloads shards one at a time and keeps only clips that clearly match that
voice. It is resumable: rerun the same command after an interruption.

The repo is a datasets.save_to_disk() dump (one .arrow file per shard,
~500 MB / ~1000 clips each, 44.1 kHz), not parquet, so shards are fetched with
hf_hub_download and opened with Dataset.from_file.

Output: <out>/wavs/000001.wav ... and <out>/raw.tsv (file<TAB>text).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
import torch
from datasets import Audio, Dataset
from huggingface_hub import HfApi, hf_hub_download
from tqdm import tqdm

REPO = "kaab4321/UrduTTS"
SPLIT_ORDER = ["train", "eval", "test"]
TEXT_COL = "transcription"
AUDIO_COL = "audio"
N_VOICES = 4
EMBED_MODEL = "microsoft/wavlm-base-plus-sv"
EMBED_RATE = 16000
EMBED_MAX_SECONDS = 8.0
VOICES_FILE = Path("data/voices.npz")


def list_shards(repo):
    files = HfApi().list_repo_files(repo, repo_type="dataset")
    shards = [f for f in files if f.endswith(".arrow")]
    return sorted(shards, key=lambda f: (SPLIT_ORDER.index(f.split("/")[0]), f))


def load_shard(repo, filename):
    path = hf_hub_download(repo, filename, repo_type="dataset")
    ds = Dataset.from_file(path)
    # Keep audio as raw bytes: avoids the datasets audio-decoder dependency.
    return ds.cast_column(AUDIO_COL, Audio(decode=False))


def decode(audio):
    source = io.BytesIO(audio["bytes"]) if audio.get("bytes") else audio["path"]
    samples, sr = sf.read(source, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples, sr


class Embedder:
    def __init__(self, device):
        from transformers import AutoFeatureExtractor, WavLMForXVector

        self.device = device
        self.extractor = AutoFeatureExtractor.from_pretrained(EMBED_MODEL)
        self.model = WavLMForXVector.from_pretrained(EMBED_MODEL).to(device).eval()

    @torch.no_grad()
    def __call__(self, clips, batch_size=32):
        """clips: list of (samples, sr). Returns L2-normalised embeddings, shape (n, d)."""
        out = []
        for start in range(0, len(clips), batch_size):
            batch = []
            for samples, sr in clips[start : start + batch_size]:
                wav = soxr.resample(samples, sr, EMBED_RATE) if sr != EMBED_RATE else samples
                # The x-vector pooling yields NaN for clips under ~0.1 s (the corpus has
                # some at 0.19 s), so loop short clips up to 1 s.
                if len(wav) < EMBED_RATE:
                    wav = np.tile(wav, EMBED_RATE // max(len(wav), 1) + 1)
                batch.append(wav[: int(EMBED_MAX_SECONDS * EMBED_RATE)])
            inputs = self.extractor(batch, sampling_rate=EMBED_RATE, padding=True, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            emb = self.model(**inputs).embeddings
            out.append(torch.nn.functional.normalize(emb, dim=-1).cpu().numpy())
        return np.concatenate(out)


def center(embs, mean):
    embs = embs - mean
    return embs / np.linalg.norm(embs, axis=1, keepdims=True)


def inspect(repo):
    shards = list_shards(repo)
    sizes = {f.path: f.size for f in HfApi().list_repo_tree(repo, repo_type="dataset", recursive=True) if hasattr(f, "size")}
    for split in SPLIT_ORDER:
        names = [s for s in shards if s.startswith(split + "/")]
        gb = sum(sizes.get(s, 0) for s in names) / 1e9
        print(f"{split}: {len(names)} shards, {gb:.1f} GB")
    ds = load_shard(repo, shards[0])
    print("features:", ds.features)
    print(f"{shards[0]}: {len(ds)} clips")
    row = ds[0]
    row[AUDIO_COL] = {"path": row[AUDIO_COL].get("path"), "bytes": "<omitted>"}
    print("first row:", row)


def write_clips(out_dir, items):
    """items: list of (name, samples, sr, text)."""
    wav_dir = out_dir / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "raw.tsv", "w", encoding="utf-8", newline="\n") as tsv:
        for name, samples, sr, text in items:
            sf.write(wav_dir / name, samples, sr, subtype="PCM_16")
            tsv.write(f"{name}\t{text}\n")


def clean_text(text):
    return " ".join(str(text).split())


def cluster(repo, n_shards, embedder):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    clips, texts, embs = [], [], []
    for shard in list_shards(repo)[:n_shards]:
        ds = load_shard(repo, shard)
        shard_clips = [decode(row[AUDIO_COL]) for row in tqdm(ds, desc=f"decode {shard}")]
        embs.append(embedder(shard_clips))
        clips += shard_clips
        texts += [clean_text(t) for t in ds[TEXT_COL]]
    embs = np.concatenate(embs)
    # x-vectors of different speakers are all very similar (cosine ~0.9); removing
    # the shared mean spreads them out so the voices separate.
    mean = embs.mean(axis=0)
    embs = center(embs, mean)

    km = KMeans(n_clusters=N_VOICES, n_init=20, random_state=0).fit(embs)
    # Number voices by size, largest first, so the numbering is stable across reruns.
    order = np.argsort(-np.bincount(km.labels_, minlength=N_VOICES))
    centroids = km.cluster_centers_[order]
    centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
    sims = embs @ centroids.T
    labels = sims.argmax(axis=1)

    print(f"{len(embs)} clips from {n_shards} shards, silhouette {silhouette_score(embs, labels, metric='cosine'):.3f}")
    print("centroid similarity between voices:\n", np.round(centroids @ centroids.T, 2))
    VOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(VOICES_FILE, centroids=centroids, mean=mean)
    for v in range(N_VOICES):
        idx = np.flatnonzero(labels == v)
        own = sims[idx, v]
        hours = sum(len(clips[i][0]) / clips[i][1] for i in idx) / 3600
        print(f"voice {v + 1}: {len(idx)} clips ({len(idx) / len(embs):.0%}), {hours:.2f} h, "
              f"similarity to centroid median {np.median(own):.2f}")
        typical = idx[np.argsort(-own)[:20]]
        out = Path(f"data/listen_v{v + 1}")
        write_clips(out, [(f"{i + 1:06d}.wav", *clips[j], texts[j]) for i, j in enumerate(typical)])
    print(f"Saved {VOICES_FILE}. Listen to data/listen_v1 ... data/listen_v{N_VOICES}, then run --voice N.")


def extract(repo, voice, out_dir, hours_target, min_sim, min_margin, embedder):
    if not VOICES_FILE.exists():
        sys.exit(f"{VOICES_FILE} not found. Run --cluster first.")
    saved = np.load(VOICES_FILE)
    centroids, mean = saved["centroids"], saved["mean"]
    v = voice - 1
    if not 0 <= v < len(centroids):
        sys.exit(f"--voice must be 1..{len(centroids)}")

    wav_dir = out_dir / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    state_file = out_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"done": [], "count": 0, "seconds": 0.0}
    # Drop any rows written after the last completed shard (interrupted run).
    tsv_path = out_dir / "raw.tsv"
    lines = tsv_path.read_text(encoding="utf-8").splitlines()[: state["count"]] if tsv_path.exists() else []
    tsv_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    for shard in list_shards(repo):
        if state["seconds"] >= hours_target * 3600:
            break
        if shard in state["done"]:
            continue
        ds = load_shard(repo, shard)
        clips = [decode(row[AUDIO_COL]) for row in tqdm(ds, desc=f"decode {shard}")]
        sims = center(embedder(clips), mean) @ centroids.T
        best = np.sort(sims, axis=1)
        margin = best[:, -1] - best[:, -2]
        keep = (sims.argmax(axis=1) == v) & (sims[:, v] >= min_sim) & (margin >= min_margin)
        texts = ds[TEXT_COL]
        with open(tsv_path, "a", encoding="utf-8", newline="\n") as tsv:
            for i in np.flatnonzero(keep):
                samples, sr = clips[i]
                state["count"] += 1
                name = f"{state['count']:06d}.wav"
                sf.write(wav_dir / name, samples, sr, subtype="PCM_16")
                tsv.write(f"{name}\t{clean_text(texts[i])}\n")
                state["seconds"] += len(samples) / sr
        state["done"].append(shard)
        state_file.write_text(json.dumps(state))
        print(f"{shard}: kept {keep.sum()}/{len(ds)}; total {state['count']} clips, {state['seconds'] / 3600:.2f} h")

    print(f"Voice {voice}: {state['count']} clips, {state['seconds'] / 3600:.2f} h in {out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--cluster", action="store_true", help="find the voices in the first --shards shards")
    ap.add_argument("--shards", type=int, default=2)
    ap.add_argument("--voice", type=int, default=None, help="voice number from --cluster")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--hours", type=float, default=15.0, help="stop once this much audio is kept")
    ap.add_argument("--min-sim", type=float, default=0.0, help="minimum cosine similarity to the voice centroid")
    ap.add_argument("--min-margin", type=float, default=0.05, help="lead over the second-closest voice")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.inspect:
        return inspect(args.repo)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if args.cluster:
        return cluster(args.repo, args.shards, Embedder(device))
    if args.voice and args.out:
        return extract(args.repo, args.voice, args.out, args.hours, args.min_sim, args.min_margin, Embedder(device))
    sys.exit("Pass --inspect, --cluster, or --voice N --out DIR.")


if __name__ == "__main__":
    main()
