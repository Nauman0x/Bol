"""LiveKit TTS plugin for BOL's self-hosted Urdu voices (urdu-tts/server/serve.py).

The voices are Piper (VITS) models fine-tuned on Urdu; Piper is GPL-3.0, so it
runs as its own HTTP service and this plugin only speaks to it over HTTP —
nothing here imports Piper. The server normalises the text itself (numbers to
words, English loanwords in Latin script to Urdu spelling, pronunciation
fixes), so the LLM's output is sent as-is.

``POST {base_url}/tts {"text", "voice"}`` streams raw 16-bit mono PCM one
sentence at a time, so playback starts after the first sentence is synthesised
(~0.1-0.3 s on CPU) rather than after the whole reply. Like Chatterbox this is
not framework-level streaming (``TTSCapabilities(streaming=False)``):
livekit-agents still splits the reply into sentences and calls synthesize()
once per sentence.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

NUM_CHANNELS = 1
# Piper "medium" voices are 22.05 kHz; the server reports the real rate per
# voice in /voices and the X-Sample-Rate header.
DEFAULT_SAMPLE_RATE = 22050


@dataclass
class _TTSOptions:
    base_url: str
    voice_id: str
    sample_rate: int


class PiperTTS(tts.TTS):
    def __init__(
        self,
        *,
        base_url: str,
        voice_id: str,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=NUM_CHANNELS,
        )
        self._opts = _TTSOptions(
            base_url=base_url.rstrip("/"), voice_id=voice_id, sample_rate=sample_rate
        )
        self._session = http_session

    @property
    def model(self) -> str:
        return "piper-urdu"

    @property
    def provider(self) -> str:
        return "Piper"

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class ChunkedStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: PiperTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: PiperTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        opts = self._tts._opts
        try:
            async with self._tts._ensure_session().post(
                f"{opts.base_url}/tts",
                json={"text": self._input_text, "voice": opts.voice_id},
                timeout=aiohttp.ClientTimeout(total=30, sock_connect=self._conn_options.timeout),
            ) as resp:
                resp.raise_for_status()
                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=int(resp.headers.get("X-Sample-Rate", opts.sample_rate)),
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                )
                async for chunk, _ in resp.content.iter_chunks():
                    if chunk:
                        output_emitter.push(chunk)
                output_emitter.flush()
        except TimeoutError:
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message, status_code=e.status, request_id=None, body=None
            ) from None
        except Exception as e:
            raise APIConnectionError() from e
