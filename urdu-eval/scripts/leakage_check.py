"""Check that benchmark sentences do not appear in a TTS/ASR training set.

    python scripts/leakage_check.py <metadata.csv ...>      (Piper csv: file|text)
Reports exact matches (after Urdu normalisation) and near-duplicates (word-level Jaccard >= 0.8).
"""
import csv, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "urdu-tts" / "scripts"))
from normalize_ur import PUNCT, normalize  # noqa: E402

STRIP = re.compile(rf"[ً-ْٰ{PUNCT}\-]")
def comp(t): return " ".join(STRIP.sub(" ", normalize(t)).split())

bench = []
with open(ROOT / "data" / "sentences.tsv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["ref"]:
            bench.append((r["id"], comp(r["ref"])))
sys.stdout.reconfigure(encoding="utf-8")
for path in sys.argv[1:]:
    train = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        train.append(comp(line.split("|", 1)[-1]))
    tset = set(train)
    exact = [i for i, t in bench if t in tset]
    tw = [set(t.split()) for t in train]
    near = []
    for i, t in bench:
        w = set(t.split())
        best = max((len(w & x) / max(1, len(w | x)) for x in tw), default=0)
        if best >= 0.8 and i not in exact:
            near.append((i, round(best, 2)))
    print(f"{path}: {len(train)} train lines | exact matches {len(exact)} {exact} | near-duplicates {len(near)} {near}")
