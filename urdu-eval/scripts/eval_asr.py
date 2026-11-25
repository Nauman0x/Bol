"""Score any speech-recognition model on the frozen classmate-recording benchmark.

    python scripts/eval_asr.py --model openai/whisper-large-v3-turbo
    python scripts/eval_asr.py --model <path-or-hf-id-of-your-finetune> --tag my_finetune

Protocol (written down so every model is scored the same way):
  * audio: data/manifest.tsv clips, 16 kHz mono, loudness-normalised to -23 dBFS RMS (peak-limited),
    because the home recordings are very quiet. Same audio for every model.
  * text: reference and hypothesis go through the project's Urdu normaliser (urdu-tts/scripts/normalize_ur.py),
    then diacritics and punctuation are removed. In the "numbers" group, digit runs in the hypothesis are
    split into single digits, because the reference is read digit by digit.
  * free-speech clips have no reference and are skipped.
  * metrics: corpus WER and CER (total errors / total reference words or characters), with 95% bootstrap
    intervals over utterances, plus per-group results. With few speakers the interval only reflects
    sentence variation, not speaker variation; resample by speaker once there are several.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import jiwer
import numpy as np
import soundfile as sf
import soxr

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT.parent / "urdu-tts" / "scripts"))
from normalize_ur import PUNCT, normalize  # noqa: E402

_STRIP = re.compile(rf"[ً-ْٰ{PUNCT}\-]")
_LATIN = re.compile(r"[A-Za-z]")


def comparable(text: str, split_digits: bool = False) -> str:
    if split_digits:
        text = re.sub(r"\d+", lambda m: " " + " ".join(m.group()) + " ", text)
    return " ".join(_STRIP.sub(" ", normalize(text)).split())


def load_audio(path: Path, target_rms_db: float = -23.0) -> np.ndarray:
    x, sr = sf.read(path, dtype="float32")
    if sr != 16000:
        x = soxr.resample(x, sr, 16000)
    rms = float(np.sqrt(np.mean(x**2))) + 1e-9
    gain = min(10 ** ((target_rms_db - 20 * np.log10(rms)) / 20), 0.95 / (float(np.abs(x).max()) + 1e-9))
    return (x * gain).astype(np.float32)


def errors(ref: str, hyp: str, unit: str) -> tuple[int, int]:
    """(edit operations, reference length) for words or characters."""
    if unit == "word":
        o = jiwer.process_words(ref, hyp)
        return o.substitutions + o.deletions + o.insertions, len(ref.split())
    o = jiwer.process_characters(ref, hyp)
    return o.substitutions + o.deletions + o.insertions, len(ref)


def boot_ci(e: np.ndarray, n: np.ndarray, iters: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(e), size=(iters, len(e)))
    r = e[idx].sum(1) / n[idx].sum(1)
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/whisper-large-v3-turbo")
    ap.add_argument("--tag", default=None, help="name for the results file (default: model id)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--manifest", type=Path, default=DATA / "manifest.tsv")
    ap.add_argument("--exclude-flagged", action="store_true", help="drop clips with QC flags")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    import torch
    from transformers import pipeline

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    asr = pipeline(
        "automatic-speech-recognition", model=args.model, device=device,
        dtype=torch.float16 if device.startswith("cuda") else torch.float32,
    )

    with open(args.manifest, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if r["ref"] and "invalid_stimulus" not in r["flags"]]
    if args.exclude_flagged:
        rows = [r for r in rows if not r["flags"]]

    out = []
    for r in rows:
        audio = load_audio(DATA / r["wav"])
        res = asr(
            {"raw": audio, "sampling_rate": 16000},
            return_timestamps=len(audio) / 16000 > 29,
            generate_kwargs={"language": "urdu", "task": "transcribe", "no_repeat_ngram_size": 4},
        )
        raw_hyp = res["text"]
        digits = r["group"] == "numbers"
        ref = comparable(r["ref"])
        hyp = comparable(raw_hyp, split_digits=digits)
        capped = len(hyp) > 2 * len(ref) + 10
        hyp = hyp[: 2 * len(ref) + 10]
        we, wn = errors(ref, hyp, "word")
        ce, cn = errors(ref, hyp, "char")
        letters = [c for c in raw_hyp if c.isalpha()]
        out.append({
            "speaker_id": r["speaker_id"], "sentence_id": r["sentence_id"], "group": r["group"], "flags": r["flags"],
            "w_err": we, "w_n": wn, "c_err": ce, "c_n": cn, "capped": int(capped),
            "latin_pct": round(100 * sum(bool(_LATIN.match(c)) for c in letters) / max(1, len(letters)), 1),
            "ref": ref, "hyp": hyp,
        })

    tag = (args.tag or args.model).replace("/", "_")
    res_path = ROOT / "results" / f"asr_{tag}.tsv"
    with open(res_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), delimiter="\t")
        w.writeheader()
        w.writerows(out)

    def summarise(sub: list[dict], label: str) -> None:
        we = np.array([o["w_err"] for o in sub]); wn = np.array([o["w_n"] for o in sub])
        ce = np.array([o["c_err"] for o in sub]); cn = np.array([o["c_n"] for o in sub])
        wl, wh = boot_ci(we, wn); cl, ch = boot_ci(ce, cn)
        print(f"{label:<12} n={len(sub):<3} WER {we.sum() / wn.sum():6.1%} [{wl:.1%}, {wh:.1%}]   "
              f"CER {ce.sum() / cn.sum():6.1%} [{cl:.1%}, {ch:.1%}]")

    print(f"\nmodel: {args.model}   clips scored: {len(out)}   hypotheses capped (loops): {sum(o['capped'] for o in out)}")
    summarise(out, "ALL")
    for g in ("casual", "business", "numbers", "codeswitch"):
        sub = [o for o in out if o["group"] == g]
        if sub:
            summarise(sub, g)
    print("wrote", res_path)


if __name__ == "__main__":
    main()
