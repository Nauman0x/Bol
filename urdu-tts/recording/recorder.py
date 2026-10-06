"""Local recording studio for the voice dataset.

    python recording/recorder.py            # then open http://localhost:8765
    python recording/recorder.py --speaker me --script recording/script.txt

Shows one sentence at a time from the script, records it in the browser as
uncompressed 48 kHz WAV (echo cancellation, noise suppression and auto gain
switched off: they distort the voice and the model would learn that), checks
the take for noise, clipping and level, and saves it to
recordings/<speaker>/wavs/NNNN.wav. raw.tsv (file<TAB>text) is rewritten after
every save, ready for scripts/prepare_dataset.py. Re-recording a sentence
replaces its file. Stdlib only, so it runs with the Windows Python.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
LOCK = threading.Lock()


def load_script(path: Path) -> list[str]:
    lines = [" ".join(l.split()) for l in path.read_text(encoding="utf-8").splitlines()]
    return [l for l in lines if l and not l.startswith("#")]


class Studio:
    def __init__(self, script: Path, out: Path):
        self.sentences = load_script(script)
        self.out = out
        self.wavs = out / "wavs"
        self.wavs.mkdir(parents=True, exist_ok=True)
        self.meta_path = out / "takes.json"
        self.meta = json.loads(self.meta_path.read_text(encoding="utf-8")) if self.meta_path.exists() else {}

    def name(self, i: int) -> str:
        return f"{i + 1:04d}.wav"

    def state(self) -> dict:
        return {
            "sentences": self.sentences,
            "takes": self.meta,
            "total_seconds": sum(t["seconds"] for t in self.meta.values()),
        }

    def save(self, i: int, wav: bytes, stats: dict) -> None:
        if not 0 <= i < len(self.sentences):
            raise ValueError("sentence index out of range")
        if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
            raise ValueError("not a WAV file")
        with LOCK:
            tmp = self.wavs / (self.name(i) + ".part")
            tmp.write_bytes(wav)
            tmp.replace(self.wavs / self.name(i))
            self.meta[str(i)] = {k: stats.get(k) for k in ("seconds", "snr_db", "peak", "speech_db", "warnings")}
            self.meta_path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=0), encoding="utf-8")
            rows = sorted(int(k) for k in self.meta)
            (self.out / "raw.tsv").write_text(
                "".join(f"{self.name(r)}\t{self.sentences[r]}\n" for r in rows), encoding="utf-8"
            )


def make_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self.send(200, (HERE / "recorder.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self.send(200, json.dumps(studio.state(), ensure_ascii=False).encode(), "application/json")
            elif path.startswith("/take/"):
                f = studio.wavs / Path(path).name
                if f.exists():
                    self.send(200, f.read_bytes(), "audio/wav")
                else:
                    self.send(404, b"", "text/plain")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/api/save":
                return self.send(404, b"not found", "text/plain")
            q = parse_qs(url.query)
            try:
                i = int(q["i"][0])
                stats = json.loads(q.get("stats", ["{}"])[0])
                body = self.rfile.read(int(self.headers["Content-Length"]))
                studio.save(i, body, stats)
            except (KeyError, ValueError) as e:
                return self.send(400, str(e).encode(), "text/plain")
            self.send(200, json.dumps({"ok": True, "total_seconds": studio.state()["total_seconds"]}).encode(),
                      "application/json")

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, default=HERE / "script.txt")
    ap.add_argument("--speaker", default="me")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    out = HERE.parent / "recordings" / args.speaker
    studio = Studio(args.script, out)
    print(f"{len(studio.sentences)} sentences, {len(studio.meta)} already recorded; saving to {out}")
    print(f"Open http://localhost:{args.port} in Chrome or Edge. Ctrl+C here to stop.")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(studio)).serve_forever()


if __name__ == "__main__":
    main()
