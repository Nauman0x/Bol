"""HTTP server for the trained Urdu Piper voices, used by BOL's `piper` TTS provider.

    python server/serve.py --voices export --port 8030      # from the urdu-tts folder, piper venv active

Runs as its own process because Piper is GPL-3.0: BOL talks to it over HTTP
(backend/worker/piper_tts.py) and never imports Piper.

    GET  /health            -> {"ok": true, "voices": N}
    GET  /voices            -> [{"id", "label", "languages": ["ur"], "sample_rate"}]
    POST /tts               {"text": "...", "voice": "<id>"}
                            -> raw 16-bit mono PCM, streamed one sentence at a time
                               (X-Sample-Rate header), until the connection closes

Text goes through the same normalisation as training (scripts/normalize_ur.py)
plus the English, Urdu-fix and phoneme lexicons in lexicon/, so "aap ka order"
style text from the LLM with English words in Latin script is spoken correctly.
Sampling settings come from each voice's .onnx.json "inference" block.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from normalize_ur import load_lexicons, normalize  # noqa: E402
from piper import PiperVoice  # noqa: E402

LEXICONS = [ROOT / "lexicon" / name for name in ("english_ur.tsv", "urdu_fix.tsv", "phonemes.tsv")]
MAX_TEXT_CHARS = 2000

logger = logging.getLogger("urdu-tts")


def voice_id(path: Path) -> str:
    """export/ur_PK-bol_rasa_female-medium.onnx -> rasa_female"""
    stem = path.name.removesuffix(".onnx")
    stem = stem.removeprefix("ur_PK-").removeprefix("bol_")
    return stem.rsplit("-", 1)[0] if stem.endswith(("-medium", "-high", "-low")) else stem


class Voices:
    def __init__(self, folder: Path):
        self.voices: dict[str, PiperVoice] = {}
        self.info: list[dict] = []
        for onnx in sorted(folder.glob("*.onnx")):
            if not Path(str(onnx) + ".json").exists():
                continue
            vid = voice_id(onnx)
            voice = PiperVoice.load(str(onnx))
            self.voices[vid] = voice
            self.info.append({
                "id": vid,
                "label": vid.replace("_", " ").title() + " (Urdu)",
                "languages": ["ur"],
                "sample_rate": voice.config.sample_rate,
            })
            logger.info("loaded voice %s from %s", vid, onnx.name)
        if not self.voices:
            raise SystemExit(f"No voices (*.onnx + *.onnx.json) in {folder}")
        self.lexicon = load_lexicons(p for p in LEXICONS if p.exists())


def make_handler(voices: Voices):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # body ends when the connection closes: simple streaming

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

        def send_json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"ok": True, "voices": len(voices.voices)})
            elif self.path == "/voices":
                self.send_json(200, voices.info)
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/tts":
                return self.send_json(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                text = str(req.get("text", "")).strip()[:MAX_TEXT_CHARS]
                vid = req.get("voice") or next(iter(voices.voices))
                voice = voices.voices[vid]
            except (ValueError, KeyError):
                return self.send_json(400, {"error": "need JSON {text, voice}; voices: " + ", ".join(voices.voices)})

            started = time.perf_counter()
            spoken = normalize(text, voices.lexicon)
            self.send_response(200)
            self.send_header("Content-Type", "audio/pcm")
            self.send_header("X-Sample-Rate", str(voice.config.sample_rate))
            self.end_headers()
            first = None
            try:
                for chunk in voice.synthesize(spoken):
                    if first is None:
                        first = time.perf_counter() - started
                    self.wfile.write(chunk.audio_int16_bytes)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return  # caller hung up or barged in
            logger.info("voice=%s chars=%d first_audio=%.0fms total=%.0fms", vid, len(text),
                        (first or 0) * 1000, (time.perf_counter() - started) * 1000)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", type=Path, default=ROOT / "export")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8030)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    voices = Voices(args.voices)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(voices))
    server.daemon_threads = True
    logger.info("serving %d voice(s) on http://%s:%d", len(voices.voices), args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
