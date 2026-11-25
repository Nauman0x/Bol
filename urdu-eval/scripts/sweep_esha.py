"""Choose decoding settings for the Esha voice without tuning on the sentences we report.

    python scripts/sweep_esha.py

Esha's 80 held-out sentences are split by position: even positions = TUNE half, odd positions = REPORT half.
Every (checkpoint, noise_scale, noise_w) setting is synthesised on the TUNE half only and scored by Whisper
(CER). The best setting is written to results/esha_sweep.json. The REPORT half is only used afterwards,
once, with the chosen setting (synth_esha.py --half report).

A scoring run whose transcripts come out far too short (a glitch seen once) is repeated automatically.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from eval_asr import comparable, errors, load_audio  # noqa: E402

TTS = Path.home() / "urdu-tts"
CK = TTS / "runs_esha/lightning_logs/version_2/checkpoints"
CKPTS = {"epoch149_last": CK / "last.ckpt", "epoch110_best_mel": next(CK.glob("epoch=110-*.ckpt"))}
NOISE_SCALE = [0.667, 0.5, 0.4, 0.3]
NOISE_W = [0.8, 1.0]


def tune_items() -> list[tuple[str, str]]:
    items = []
    for line in (TTS / "data/esha/test.csv").read_text(encoding="utf-8").splitlines():
        name, _, text = line.partition("|")
        if text.strip():
            items.append((Path(name).stem, text.strip()))
    return items[0::2]


def synth(ckpt: Path, ns: float, nw: float, texts: list[str], out: Path) -> None:
    tf = out / "in.txt"
    tf.write_text("\n".join(texts) + "\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(TTS / "scripts")}
    p = subprocess.run(
        [sys.executable, str(TTS / "scripts/synth.py"), "--model", str(ckpt),
         "--config", str(TTS / "runs_esha/ur_PK-bol_esha-medium.onnx.json"),
         "--text-file", str(tf), "--out", str(out), "--noise-scale", str(ns), "--noise-w", str(nw)],
        cwd=TTS, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode:
        sys.exit(p.stderr[-1500:])


def main() -> None:
    import torch
    from transformers import pipeline

    sys.stdout.reconfigure(encoding="utf-8")
    device = os.environ.get("SWEEP_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        torch.set_num_threads(int(os.environ.get("SWEEP_THREADS", "6")))  # leave cores for other jobs
    asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", device=device,
                   dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    print("device:", device)
    items = tune_items()
    refs = [comparable(t) for _, t in items]

    def score(d: Path) -> tuple[float, float, float]:
        e = n = we = wn = 0
        ratio = []
        for i, ref in enumerate(refs, start=1):
            res = asr({"raw": load_audio(d / f"{i:04d}.wav"), "sampling_rate": 16000},
                      generate_kwargs={"language": "urdu", "task": "transcribe", "no_repeat_ngram_size": 4})
            hyp = comparable(res["text"])[: 2 * len(ref) + 10]
            ce, cn = errors(ref, hyp, "char")
            w_e, w_n = errors(ref, hyp, "word")
            e += ce; n += cn; we += w_e; wn += w_n
            ratio.append(len(hyp) / max(1, len(ref)))
        return e / n, we / wn, float(np.median(ratio))

    results = []
    print(f"tuning on {len(items)} sentences (even positions of the 80 held-out)")
    print(f"{'checkpoint':<20}{'noise':>7}{'noise_w':>9}{'CER':>8}{'WER':>8}")
    for (cname, ck), ns, nw in itertools.product(CKPTS.items(), NOISE_SCALE, NOISE_W):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as td:
            d = Path(td)
            synth(ck, ns, nw, [t for _, t in items], d)
            cer, wer, ratio = score(d)
            if ratio < 0.6:  # transcripts far too short: scoring glitch, not the voice
                print("  (suspicious transcripts, rescoring)")
                cer, wer, ratio = score(d)
        results.append({"ckpt": cname, "noise_scale": ns, "noise_w": nw, "cer": cer, "wer": wer})
        print(f"{cname:<20}{ns:>7}{nw:>9}{cer:>8.1%}{wer:>8.1%}", flush=True)

    best = min(results, key=lambda r: r["cer"])
    default = next(r for r in results if r["ckpt"] == "epoch149_last" and r["noise_scale"] == 0.667 and r["noise_w"] == 0.8)
    out = {"tune_set": "even positions of esha test.csv", "best": best, "default": default, "all": results}
    (ROOT / "results" / "esha_sweep.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nbest: {best}\ndefault: {default}")


if __name__ == "__main__":
    main()
