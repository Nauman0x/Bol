"""Dump validation mel loss per epoch from the TensorBoard logs of the two final runs.

    python report/results/extract_curves.py > curves.json
"""
import glob
import json
import os

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

RUNS = {"male": "~/urdu-tts/runs_rasa", "female": "~/urdu-tts/runs_rasa_f"}


def curve(run):
    points = {}
    for path in sorted(glob.glob(os.path.expanduser(run) + "/lightning_logs/version_*/events.out.tfevents.*")):
        ea = EventAccumulator(path, size_guidance={"scalars": 0, "audio": 1, "images": 1, "histograms": 1, "tensors": 1})
        ea.Reload()
        tags = ea.Tags()["scalars"]
        if "val_mel" not in tags or "epoch" not in tags:
            continue
        epoch_at_step = {e.step: int(e.value) for e in ea.Scalars("epoch")}
        for e in ea.Scalars("val_mel"):
            if e.step in epoch_at_step:
                points[epoch_at_step[e.step]] = round(e.value, 4)
    return dict(sorted(points.items()))


print(json.dumps({name: curve(run) for name, run in RUNS.items()}))
