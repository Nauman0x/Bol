"""Build listening-test stimuli v2 from Esha's REPORT half (sentences never used to pick settings).

    python scripts/prep_listening_esha.py        # after: synth_esha.py --half report <chosen settings>

Systems (all on the same sentences, same loudness/trim treatment):
  esha_real        Esha's real recording of the held-out sentence (human ceiling, same speaker as the voice)
  esha_voice       our Piper voice trained on Esha
  bol_rasa_female  earlier voice trained on Indian-Urdu Rasa speech
  stock_fasih      stock Piper Urdu voice
  anchor           the real recording, deliberately degraded (see prep_listening.degrade)

Writes data/listening_esha/<system>/<id>.wav and data/listening_esha/stimuli.tsv (group = "esha").
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prep_listening import SR, degrade, level, load, trim  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "listening_esha"
SYSTEMS = ["esha_real", "esha_voice", "bol_rasa_female", "stock_fasih"]


def main() -> None:
    with open(DATA / "esha_manifest_esha_real.tsv", encoding="utf-8-sig", newline="") as f:
        ids = [r["sentence_id"] for r in csv.DictReader(f, delimiter="\t")]
    OUT.mkdir(exist_ok=True)
    rows = []
    for sid in ids:
        clips = {s: load(DATA / "esha" / s / f"{sid}.wav") for s in SYSTEMS}
        clips["anchor"] = degrade(level(trim(clips["esha_real"])), seed=int(sid))
        for system, x in clips.items():
            y = level(trim(x))
            (OUT / system).mkdir(exist_ok=True)
            sf.write(OUT / system / f"{sid}.wav", y, SR, subtype="PCM_16")
            rows.append({"sentence_id": sid, "group": "esha", "system": system,
                         "file": f"{system}/{sid}.wav", "seconds": round(len(y) / SR, 2)})
    with open(OUT / "stimuli.tsv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    mb = sum((OUT / r["file"]).stat().st_size for r in rows) / 1e6
    print(f"{len(ids)} sentences x {len(SYSTEMS) + 1} systems = {len(rows)} clips, {mb:.1f} MB")
    for s in [*SYSTEMS, "anchor"]:
        print(f"  {s:<16} mean {np.mean([r['seconds'] for r in rows if r['system'] == s]):.1f}s")


if __name__ == "__main__":
    main()
