#!/usr/bin/env python3
"""
BOL: Rakht-e-safar (Sumbal Babar) -> clean single-sentence clips of the host only.

  python bol_pipeline.py download                 # 1. original audio from the RSS feed
  python bol_pipeline.py wav                      # 2. convert once to WAV (mono, 44.1 kHz, 16-bit)
  python bol_pipeline.py clips episodes_wav/ep001.wav ...   # 3-5. diarize, transcribe, cut sentences
  python bol_pipeline.py speakercheck             # 7. score every clip against the host's voice
  python bol_pipeline.py speakercheck --apply     #    ...and move clips that don't match to rejected/

No audio processing is done anywhere: clips are exact sample slices of the WAV.
"""
import argparse, json, os, re, subprocess
from collections import Counter
from types import SimpleNamespace
from pathlib import Path
import numpy as np

FEED = "https://anchor.fm/s/120e678c/podcast/rss"
OUT = Path("podcast_sumbalbabar")
WAVS = OUT / "wavs"
MIN_DUR, MAX_DUR = 2.0, 12.0


# ---------- 1. download ----------
def cmd_download(a):
    import feedparser, requests
    d = Path("episodes_raw"); d.mkdir(exist_ok=True)
    entries = list(reversed(feedparser.parse(FEED).entries))  # feed is newest-first
    with open(d / "episodes.tsv", "w", encoding="utf-8") as idx:
        for i, e in enumerate(entries, 1):
            url = next((l.href for l in e.get("links", []) if l.get("rel") == "enclosure"), None)
            if not url:
                continue
            ext = os.path.splitext(url.split("?")[0])[1]
            ext = ext if 2 <= len(ext) <= 5 else ".mp3"
            path = d / f"ep{i:03d}{ext}"
            idx.write(f"ep{i:03d}\t{e.get('title', '')}\t{e.get('published', '')}\n")
            if path.exists():
                continue
            print("downloading", path.name, "-", e.get("title", ""))
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)


# ---------- 2. convert to WAV once ----------
def cmd_wav(a):
    src, dst = Path("episodes_raw"), Path("episodes_wav"); dst.mkdir(exist_ok=True)
    for f in sorted(src.glob("ep*.*")):
        if f.suffix == ".tsv":
            continue
        out = dst / (f.stem + ".wav")
        if not out.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(f),
                            "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", str(out)], check=True)
            print("wrote", out)


# ---------- helpers ----------
def to_sec(t):
    t = t.strip()
    if t == "end":
        return float("inf")
    sec = 0.0
    for x in t.split(":"):
        sec = sec * 60 + float(x)
    return sec


def load_skips():
    """skip.tsv: episode<TAB>start<TAB>end  (e.g. ep001  0:00  0:45) for intros, ads, music."""
    skips, p = {}, Path("skip.tsv")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                ep, s, e = line.split("\t")[:3]
                skips.setdefault(ep.strip(), []).append((to_sec(s), to_sec(e)))
    return skips


def overlap(a0, a1, intervals):
    return sum(max(0.0, min(a1, b1) - max(a0, b0)) for b0, b1 in intervals)


def pauses(x, sr, frame=0.02, min_len=0.25, above_floor=4.0):
    """(start, end) of quiet stretches, from loudness. The floor is per episode because of background music."""
    k = int(frame * sr); n = len(x) // k
    db = 10 * np.log10(((x[:n * k].astype(np.float32).reshape(n, k) / 32768.0) ** 2).mean(1) + 1e-12)
    quiet = np.concatenate([[False], db < np.percentile(db, 10) + above_floor, [False]])
    edges = np.flatnonzero(np.diff(quiet.astype(np.int8)))
    return [(a * frame, b * frame) for a, b in zip(edges[::2], edges[1::2]) if (b - a) * frame >= min_len]


def cut_points(ps, total):
    """Clip boundaries in the middle of pauses: end a clip at a long pause once it is >= 3 s, at any pause once >= 6 s."""
    cuts, start = [], 0.0
    for a, b in ps:
        mid, dur = (a + b) / 2, (a + b) / 2 - start
        if (b - a >= 0.4 and dur >= 3.0) or dur >= 6.0 or (dur >= MIN_DUR and b - a >= 0.8):
            cuts.append((start, mid)); start = mid
    cuts.append((start, total))
    return cuts


def next_number():
    nums = [int(p.stem) for d in (WAVS, OUT / "rejected") if d.exists()
            for p in d.glob("*.wav") if p.stem.isdigit()]
    return max(nums, default=0)


# ---------- 3-5. diarize, transcribe, cut ----------
def cmd_clips(a):
    import soundfile as sf, torch
    from faster_whisper import WhisperModel
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    # ponytail: no HF_TOKEN -> no diarization; speakercheck alone enforces the single voice
    diar = None
    if os.environ.get("HF_TOKEN"):
        from pyannote.audio import Pipeline
        diar = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
                                        use_auth_token=os.environ["HF_TOKEN"])
        diar.to(torch.device(dev))
    asr = None

    WAVS.mkdir(parents=True, exist_ok=True)
    skips, n = load_skips(), next_number()
    srcf = OUT / "sources.tsv"
    done = {l.split("\t")[1] for l in srcf.read_text(encoding="utf-8").splitlines() if l} if srcf.exists() else set()

    for wav in map(Path, a.wavs):
        ep = wav.stem
        if ep in done:
            print("already done:", ep); continue

        turns = {"ALL": [(0.0, float("inf"))]}
        if diar:
            print("diarizing", ep)
            turns = {}
            for seg, _, spk in diar(str(wav)).itertracks(yield_label=True):
                turns.setdefault(spk, []).append((seg.start, seg.end))
        host = max(turns, key=lambda s: sum(e - b for b, e in turns[s]))
        host_turns = turns[host]
        others = [t for s, ts in turns.items() if s != host for t in ts]

        cache = Path("transcripts") / f"{ep}.json"   # transcribe once, re-cut for free
        if not cache.exists():
            print("transcribing", ep)
            asr = asr or WhisperModel("large-v3-turbo", device=dev,
                                      compute_type="float16" if dev == "cuda" else "int8")
            segs, _ = asr.transcribe(str(wav), language="ur", word_timestamps=True, vad_filter=True,
                                     beam_size=5, condition_on_previous_text=False)
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps([[w.word, w.start, w.end, w.probability] for s in segs
                                         for w in (s.words or []) if w.word.strip()],
                                        ensure_ascii=False), encoding="utf-8")
        words = [SimpleNamespace(word=w, start=b, end=e, probability=p)
                 for w, b, e, p in json.loads(cache.read_text(encoding="utf-8"))]

        audio, sr = sf.read(str(wav), dtype="int16")
        bad = skips.get(ep, [])
        kept, why = 0, Counter()
        with open(OUT / "raw.tsv", "a", encoding="utf-8") as raw, \
             open(srcf, "a", encoding="utf-8") as src, \
             open(OUT / "review.tsv", "a", encoding="utf-8") as rev:
            for s, e in cut_points(pauses(audio, sr), len(audio) / sr):
                c = [w for w in words if s <= (w.start + w.end) / 2 < e]
                seg = audio[int(s * sr):int(e * sr)]
                reason = ("no_words" if not c else "short" if e - s < MIN_DUR else "long" if e - s > MAX_DUR else
                          "skip.tsv" if overlap(s, e, bad) > 0 else                 # intro/ad/music you marked
                          "other_voice" if overlap(s, e, others) > 0.2 else         # second voice nearby
                          "not_host" if overlap(s, e, host_turns) < 0.8 * (e - s) else None)
                if reason:
                    why[reason] += 1; continue
                text = " ".join(w.word.strip() for w in c)
                minp = min(w.probability for w in c)
                flags = [f for f, hit in (("latin", re.search(r"[A-Za-z]", text)),
                                          ("digits", re.search(r"[0-9۰-۹]", text)),
                                          ("low_conf", minp < 0.5)) if hit]
                n += 1; kept += 1; name = f"{n:04d}.wav"
                sf.write(str(WAVS / name), seg, sr, subtype="PCM_16")
                raw.write(f"{name}\t{text}\n")
                src.write(f"{name}\t{ep}\t{s:.3f}\t{e:.3f}\n")
                rev.write(f"{name}\t{ep}\t{e - s:.2f}\t{minp:.2f}\t{','.join(flags)}\n")
        print(f"{ep}: kept {kept} clips, dropped {dict(why)} (host = {host}, speakers = {len(turns)})")


# ---------- 7. same-speaker check ----------
def drop_rows(path, bad):
    if path.exists():
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l and l.split("\t")[0] not in bad]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_speakercheck(a):
    import soundfile as sf, torch, torchaudio
    from speechbrain.inference.speaker import EncoderClassifier
    norm = lambda v: torch.nn.functional.normalize(v, dim=-1)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", savedir="ecapa",
                                         run_opts={"device": dev})
    names = sorted(p.name for p in WAVS.glob("*.wav"))
    embs = []
    for nm in names:
        x, sr = sf.read(str(WAVS / nm), dtype="float32")
        t = torchaudio.functional.resample(torch.from_numpy(x).unsqueeze(0), sr, 16000)  # in memory only
        embs.append(norm(enc.encode_batch(t.to(dev)).squeeze().cpu()))
    E = torch.stack(embs)

    if a.ref:   # clips you listened to and know are Sumbal
        ref = norm(E[[names.index(r) for r in a.ref]].mean(0))
    else:       # average voice of all clips, refined once on the ones that already match
        ref = norm(E.mean(0)); sims = E @ ref
        if (sims >= a.threshold).any():
            ref = norm(E[sims >= a.threshold].mean(0))
    sims = (E @ ref).tolist()

    order = sorted(zip(names, sims), key=lambda t: t[1])
    with open(OUT / "speaker_scores.tsv", "w", encoding="utf-8") as f:
        for nm, sc in order:
            f.write(f"{nm}\t{sc:.3f}\n")
    bad = {nm for nm, sc in order if sc < a.threshold}
    print(f"{len(bad)} of {len(names)} clips below {a.threshold}; lowest first in speaker_scores.tsv")

    if a.apply and bad:
        rej = OUT / "rejected"; rej.mkdir(exist_ok=True)
        for nm in bad:
            (WAVS / nm).rename(rej / nm)
        for p in ("raw.tsv", "sources.tsv", "review.tsv"):
            drop_rows(OUT / p, bad)
        print("moved to", rej)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download"); sub.add_parser("wav")
    c = sub.add_parser("clips"); c.add_argument("wavs", nargs="+")
    s = sub.add_parser("speakercheck")
    s.add_argument("--ref", nargs="*", help="clip names you verified are the host, e.g. 0003.wav 0017.wav")
    s.add_argument("--threshold", type=float, default=0.55)
    s.add_argument("--apply", action="store_true")
    a = p.parse_args()
    {"download": cmd_download, "wav": cmd_wav, "clips": cmd_clips, "speakercheck": cmd_speakercheck}[a.cmd](a)
