"""Custom LiveKit TTS plugin for self-hosted Chatterbox-TTS-Server's native
streaming ``/tts`` endpoint (see deploy/chatterbox/vendor/server.py).

The alternative — livekit-plugins-openai against Chatterbox's OpenAI-compatible
``/v1/audio/speech`` — hardcodes ``TTSCapabilities(streaming=False)`` and
returns a single buffered mp3 response: the caller waits for an entire
sentence to finish synthesizing server-side before any audio plays. This
plugin instead posts to ``/tts`` with ``stream: true`` and pushes the raw PCM
response to the framework as it arrives, so playback of a sentence can start
as soon as the server has produced its first chunk of that sentence's audio.
See deploy/chatterbox/README.md, "Honest caveat on latency".

Still not framework-level streaming (``TTSCapabilities(streaming=False)``):
the native endpoint synthesizes one complete text string per request — there
is no incremental/live text-input channel like Fish Audio's websocket, so
this only improves per-sentence time-to-first-byte, not turn-level
pipelining. livekit-agents still buffers input into sentences (StreamAdapter)
before calling synthesize() once per sentence, same as today.
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

# _create_wav_header() in server.py always writes a fixed 44-byte canonical
# WAV header (even though it doesn't know the final data size upfront) before
# any PCM bytes — confirmed against the vendored source. AudioEmitter is fed
# raw PCM directly (mime_type="audio/pcm" below), so this header must never
# reach it.
_WAV_HEADER_BYTES = 44


@dataclass
class _TTSOptions:
    root_url: str
    voice_id: str
    sample_rate: int
    language: str | None


class ChatterboxTTS(tts.TTS):
    def __init__(
        self,
        *,
        base_url: str,
        voice_id: str,
        language: str | None = None,
        sample_rate: int = 24000,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        """base_url follows this codebase's existing OpenAI-compatible
        convention (CHATTERBOX_BASE_URL, e.g. "http://host:8004/v1" — see
        app/config.py) so no separate setting is needed; the native
        streaming endpoint lives one level up, at the server root, not
        under /v1.

        language: an ISO-639 code (e.g. "es"), or None to let the server use
        its own configured default ("en" — see deploy/chatterbox/vendor/
        config.py's generation_defaults.language) or infer from the text.
        Without this, every synthesis ran as English regardless of the
        agent's configured language — the vendored server supports 23
        languages (Chatterbox Multilingual) but was never told which one."""
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=NUM_CHANNELS,
        )
        root_url = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
        self._opts = _TTSOptions(
            root_url=root_url.rstrip("/"),
            voice_id=voice_id,
            sample_rate=sample_rate,
            language=language,
        )
        self._session = http_session

    @property
    def model(self) -> str:
        return "chatterbox-turbo"

    @property
    def provider(self) -> str:
        return "Chatterbox"

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class ChunkedStream(tts.ChunkedStream):
    """Synthesizes via Chatterbox's native streaming /tts endpoint."""

    def __init__(
        self, *, tts: ChatterboxTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: ChatterboxTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        opts = self._tts._opts
        payload = {
            "text": self._input_text,
            "voice_mode": "predefined",
            "predefined_voice_id": opts.voice_id,
            "stream": True,
        }
        if opts.language:
            payload["language"] = opts.language

        try:
            async with self._tts._ensure_session().post(
                f"{opts.root_url}/tts",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30, sock_connect=self._conn_options.timeout),
            ) as resp:
                resp.raise_for_status()

                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=opts.sample_rate,
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                )

                header_remaining = _WAV_HEADER_BYTES
                async for chunk, _ in resp.content.iter_chunks():
                    if not chunk:
                        continue
                    if header_remaining > 0:
                        if len(chunk) <= header_remaining:
                            header_remaining -= len(chunk)
                            continue
                        chunk = chunk[header_remaining:]
                        header_remaining = 0
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
