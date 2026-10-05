"""Show training progress, one line per finished epoch, and follow new ones.

    python scripts/progress.py            # all epochs so far, then keep watching
    python scripts/progress.py --once     # print and exit

From Windows: wsl -d Ubuntu-24.04 -- ~/urdu-tts/piper1-gpl/.venv/bin/python ~/urdu-tts/scripts/progress.py

Reads the TensorBoard logs under runs/lightning_logs (the progress bar is not
written to runs/train.log because training runs without a terminal). Ctrl-C
only stops watching, not training.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import time
from datetime import datetime

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

TAGS = ["val_mel", "train_mel", "loss_g", "loss_d"]


def epochs(runs):
    """{epoch: (wall_time, {tag: value})} across all run versions."""
    rows = {}
    for path in sorted(glob.glob(f"{runs}/lightning_logs/version_*/events.out.tfevents.*")):
        ea = EventAccumulator(path, size_guidance={"scalars": 0})
        ea.Reload()
        tags = ea.Tags()["scalars"]
        if "epoch" not in tags or "val_mel" not in tags:
            continue
        step_epoch = {e.step: int(e.value) for e in ea.Scalars("epoch")}
        for e in ea.Scalars("val_mel"):
            epoch = step_epoch.get(e.step)
            if epoch is None:
                continue
            values = {}
            for tag in TAGS:
                if tag in tags:
                    near = [s for s in ea.Scalars(tag) if s.step <= e.step]
                    if near:
                        values[tag] = near[-1].value
            rows[epoch] = (e.wall_time, values)
    return rows


def running():
    return subprocess.run(["pgrep", "-f", "piper_train_fi[t]"], capture_output=True).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.expanduser("~/urdu-tts/runs"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=30, help="seconds between checks")
    args = ap.parse_args()

    print(f"{'time':8}  {'epoch':>6}  {'val_mel':>8}  {'train_mel':>9}  {'loss_g':>7}  {'loss_d':>6}  min/epoch")
    shown, prev_time = set(), None
    while True:
        for epoch, (wall, v) in sorted(epochs(args.runs).items()):
            if epoch in shown:
                prev_time = wall
                continue
            shown.add(epoch)
            per = f"{(wall - prev_time) / 60:9.1f}" if prev_time and 0 < wall - prev_time < 3600 else ""
            prev_time = wall
            print(f"{datetime.fromtimestamp(wall):%H:%M:%S}  {epoch:6d}  {v.get('val_mel', 0):8.4f}  "
                  f"{v.get('train_mel', 0):9.4f}  {v.get('loss_g', 0):7.2f}  {v.get('loss_d', 0):6.2f}  {per}",
                  flush=True)
        if args.once:
            break
        print(f"  ... {'training' if running() else 'NOT RUNNING'}, checked {datetime.now():%H:%M:%S}", end="\r", flush=True)
        time.sleep(args.every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
