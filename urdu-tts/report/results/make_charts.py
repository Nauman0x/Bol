"""Draw the two report charts from the evaluation output and the training curves.

    python report/results/make_charts.py results.txt val_mel_curves.json report/charts

Chart 1 compares, on the same test sentences, how hard the original Piper Urdu
voice and our fine-tuned voice are to understand for a speech recogniser (Whisper
character error rate, lower is better). Podcast-data rows (v1, v2) use the 20
held-out podcast sentences measured during the experiments; studio-data rows come
from results.txt (100 held-out Rasa sentences per voice). Rows are not comparable
with each other in absolute terms (different sentences) - read each pair.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE = "#2a78d6", "#eb6834"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})


def parse(path: Path) -> dict:
    """results.txt -> {(section, label): median CER %}"""
    out, section = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].split(",")[0].strip() if "held-out" in line else "casual lines"
            if "male voice" in line and "female" not in line:
                section = "male"
            elif "female voice" in line:
                section = "female"
        m = re.match(r"(\w+): .*CER median ([\d.]+)%", line)
        if m and section:
            out[(section, m.group(1))] = float(m.group(2))
    return out


def fmt(v):
    return f"{v:.1f}%" if isinstance(v, float) else f"{v}%"


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK2, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_intelligibility(r: dict, out: Path):
    rows = [  # (label, original voice %, our voice %, human recording % or None)
        ("Podcast data (1 h)\nfull fine-tune", 33, 59, None),
        ("Podcast data (1 h)\n+ warm-start, cleaned", 33, 69, None),
        ("Studio data (10 h)\nmale voice, final", r[("male", "original_piper_voice")], r[("male", "our_voice")],
         r[("male", "real_recording")]),
        ("Studio data (10 h)\nfemale voice, final", r[("female", "original_piper_voice")], r[("female", "our_voice")],
         r[("female", "real_recording")]),
    ]
    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=200, facecolor=SURFACE)
    style(ax)
    h, gap = 0.30, 0.34
    for i, (label, orig, ours, human) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.barh(y + gap / 2, orig, height=h, color=MUTED)
        ax.barh(y - gap / 2, ours, height=h, color=BLUE)
        ax.text(orig + 0.8, y + gap / 2, fmt(orig), va="center", color=INK2, fontsize=10)
        ax.text(ours + 0.8, y - gap / 2, fmt(ours), va="center", color=INK, fontsize=10, fontweight="bold")
        if human is not None:
            ax.plot([human, human], [y - 0.42, y + 0.42], color=INK, linewidth=1.4, linestyle=(0, (3, 2)))
            ax.text(human, y + 0.50, f"real human recording {fmt(human)}", ha="center", va="bottom",
                    color=INK2, fontsize=8.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows][::-1], color=INK)
    ax.set_xlim(0, 80)
    ax.set_ylim(-0.6, len(rows) - 0.1)
    ax.set_xlabel("Whisper character error rate on held-out test sentences (lower = easier to understand)",
                  color=INK2, fontsize=9.5)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    handles = [plt.Rectangle((0, 0), 1, 1, color=MUTED), plt.Rectangle((0, 0), 1, 1, color=BLUE)]
    ax.legend(handles, ["Original Piper Urdu voice", "Our fine-tuned voice"], loc="upper right",
              frameon=False, labelcolor=INK2, fontsize=9.5)
    fig.suptitle("Studio-quality data fixed intelligibility; tuning the podcast data never did",
                 x=0.02, ha="left", color=INK, fontsize=13, fontweight="bold")
    fig.text(0.02, 0.905, "Each pair is measured on the same sentences; different pairs use different sentences.",
             color=INK2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out / "intelligibility.png", facecolor=SURFACE)
    plt.close(fig)


def chart_training(curves: dict, out: Path):
    fig, ax = plt.subplots(figsize=(9.2, 4.6), dpi=200, facecolor=SURFACE)
    style(ax)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.xaxis.grid(False)
    for name, color, label in (("male", BLUE, "Male voice"), ("female", ORANGE, "Female voice")):
        xs = [int(k) for k in curves[name]]
        ys = list(curves[name].values())
        ax.plot(xs, ys, color=color, linewidth=1.8, label=label)
        ax.plot([xs[-1]], [ys[-1]], "o", color=color, markersize=6, markeredgecolor=SURFACE, markeredgewidth=2)
        ax.text(xs[-1] + 1.5, ys[-1], f"{ys[-1]:.3f}", va="center", color=INK, fontsize=10)
    ax.set_xlim(0, 128)
    ax.set_xlabel("Training epoch (one pass over ~10 h of speech)", color=INK2, fontsize=9.5)
    ax.set_ylabel("Validation mel-spectrogram loss", color=INK2, fontsize=9.5)
    ax.legend(loc="upper right", frameon=False, labelcolor=INK2, fontsize=10)
    fig.suptitle("Both voices kept improving for all 120 epochs", x=0.02, ha="left", color=INK, fontsize=13,
                 fontweight="bold")
    fig.text(0.02, 0.9, "Lower = generated speech is closer to the held-out real recordings. "
             "Levels differ between voices (different speaker and data).", color=INK2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out / "training_curves.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    results, curves_path, outdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    parsed = parse(results)
    chart_intelligibility(parsed, outdir)
    chart_training(json.loads(curves_path.read_text()), outdir)
    print("wrote", [p.name for p in outdir.glob("*.png")])
