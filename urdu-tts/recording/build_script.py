"""Merge the topic files into one recording script.

    python recording/build_script.py                       # script_female/*.txt -> script.txt
    python recording/build_script.py --parts recording/script_parts

Interleaves the topics line by line (greeting, shopping, banking, booking,
numbers, daily life, greeting, ...) so any first stretch of a recording
session covers every topic, drops duplicates and lines with Latin letters or
digits (the voice learns English loanwords in Urdu script), and prints the
estimated reading time.
"""

from __future__ import annotations

import argparse
import re
import sys
from itertools import zip_longest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAD = re.compile(r"[A-Za-z0-9٠-٩۰-۹]")
CHARS_PER_SECOND = 13  # typical relaxed conversational Urdu reading pace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=Path, default=HERE / "script_female")
    ap.add_argument("--out", type=Path, default=HERE / "script.txt")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    parts = sorted(args.parts.glob("*.txt"))
    if not parts:
        sys.exit(f"No .txt files in {args.parts}")
    topics = []
    for p in parts:
        lines = [" ".join(l.split()) for l in p.read_text(encoding="utf-8-sig").splitlines()]
        topics.append([l for l in lines if l])
        print(f"{p.name}: {len(topics[-1])} lines")

    seen, out, dropped = set(), [], []
    for row in zip_longest(*topics):
        for line in row:
            if line is None:
                continue
            if BAD.search(line):
                dropped.append(line)
            elif line not in seen:
                seen.add(line)
                out.append(line)

    args.out.write_text("".join(l + "\n" for l in out), encoding="utf-8")
    minutes = sum(len(l) for l in out) / CHARS_PER_SECOND / 60
    print(f"{len(out)} sentences -> {args.out} (about {minutes:.0f} minutes of speech; "
          f"{len(dropped)} dropped for Latin letters or digits)")
    for line in dropped[:5]:
        print("  dropped:", line)


if __name__ == "__main__":
    main()
