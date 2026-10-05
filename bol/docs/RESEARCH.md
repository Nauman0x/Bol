# BOL Stack Research (August 2026)

Research into building an AI calling platform with the least possible third-party dependence. Three areas: telephony/orchestration, LLM, and speech (TTS/STT).

---

## 1. Telephony — "no open-source option" is wrong

Nearly the whole telephony stack is open source and self-hostable: SIP signaling, media servers, SIP↔WebRTC bridging, and orchestration. The **only** unavoidable third party is a **carrier** for PSTN interconnect (real phone numbers + minutes come from licensed operators). That dependency shrinks to a cheap wholesale SIP trunk instead of Twilio's full programmable-voice stack.

### Open-source options

- **LiveKit** (Apache-2.0) — modern WebRTC SFU with a fully open-source SIP bridge ([livekit/sip](https://github.com/livekit/sip)). Self-hosting documented: Docker/K8s, Redis, port 5060 + RTP 10000–20000. Point any carrier's SIP trunk at it; calls land in rooms where agents join as participants. **← recommended**
- **Jambonz** (MIT, [jambonz.org](https://jambonz.org/)) — open-source CPaaS: the direct self-hosted Twilio Programmable Voice replacement (FreeSWITCH + Drachtio, Twilio-like verb API, BYO carrier/STT/TTS, multi-tenant portal). Best choice if BOL's product were literally programmable telephony for others.
- **FreeSWITCH** (MPL) / **Asterisk** (GPLv2) — mature engines; more ops burden, weaker AI-native tooling.
- **Kamailio / OpenSIPS** (GPL) — SIP edge proxies, only needed at carrier-grade scale.

### Carrier costs (the part you can't avoid)

| | Outbound/min | Inbound/min |
|---|---|---|
| Twilio Programmable Voice | $0.0140 | $0.0085 |
| Telnyx Elastic SIP trunk | ~$0.002–0.005 | ~$0.001–0.0032 |
| VoIP.ms | ~$0.005 | ~$0.005 |

DIDs ~$1/mo (Telnyx, VoIP.ms, DIDWW for international). At 100k min/mo: ~$500 (Telnyx) vs ~$1,300 (Twilio), before Twilio's per-feature add-ons (recording, streams) that the OSS stack does free. Roughly 60–70% cheaper on carriage.

### Orchestration frameworks

| Framework | License | Verdict |
|---|---|---|
| **LiveKit Agents** | Apache-2.0 | Production-grade, native SIP, Python/Node, Silero VAD + trained turn-detection model for barge-in, huge plugin ecosystem. **← recommended** |
| **Pipecat** (Daily) | BSD-2 | Production-grade; cleanest frame-based pipeline, best interruption control; no native SIP server (uses Twilio/Telnyx/Daily transports). Can run over LiveKit transport — adopt selectively for complex conversation logic. |
| Jambonz | MIT | Is the telephony layer itself; websocket verb API incl. `llm` verb. |
| Vocode | MIT | Maintained but trailing; momentum moved to Pipecat/LiveKit. |
| Bolna, TEN | OSS | Smaller communities / platform-shaped. |

### Managed platforms (context)

Vapi $0.10–0.30/min all-in, Retell $0.07–0.31, Bland ~$0.09 flat. Self-hosted stack: ~$0.02–0.06/min all-in — 3–10x cheaper at scale.

### Migration path

1. **MVP**: LiveKit **Cloud** + Telnyx trunk + one agent-worker VM (agent code identical to self-hosted future — key de-risking property).
2. **Growth**: autoscale agent workers; committed-use Telnyx rates; add second carrier (DIDWW/VoIP.ms) for coverage/failover.
3. **Scale**: self-host LiveKit server + `livekit/sip`; self-host speech models → ~$0.01–0.02/min.
4. **Carrier-grade** (optional): Kamailio SIP edge, multi-region, direct interconnects.

Key links: [LiveKit self-host SIP docs](https://docs.livekit.io/transport/self-hosting/sip-server/) · [SIP trunk setup](https://docs.livekit.io/telephony/start/sip-trunk-setup/) · [Telnyx Elastic SIP pricing](https://telnyx.com/pricing/elastic-sip) · [Telnyx LiveKit guide](https://developers.telnyx.com/docs/edge-compute/livekit) · [docs.pipecat.ai](https://docs.pipecat.ai) · [github.com/jambonz](https://github.com/jambonz)

---

## 2. LLM — hosted open weights first, self-host later

Voice needs time-to-first-token (TTFT) **under ~300ms**; total voice-to-voice under ~800ms. Throughput matters less than TTFT.

### Hosted fast inference (open-weight models)

Groq/Cerebras/Fireworks/Together are proprietary *services* running **open-weight models** — you avoid model lock-in (prompts, tool schemas, fine-tuning stay portable to self-hosting).

| Provider | Speed | Pricing (per 1M tok) | Verdict |
|---|---|---|---|
| **Groq** (LPU) | Sub-100ms TTFT typical; ~250–276 tok/s on Llama 3.3 70B; deterministic tail latency | 8B: $0.05/$0.08 · 70B: $0.59/$0.79 | **Best TTFT — default for voice** |
| **Cerebras** | 1,800+ tok/s (70B); TTFT slightly behind Groq | 70B: $0.85/$1.20 | Fallback / second provider |
| Fireworks / Together | Good breadth, slower TTFT | ~$0.90–1.04 (70B) | Fine-tuning platforms |
| DeepSeek official API | **TTFT ~1.7s+ — not voice-suitable** | Cheapest per token | Use only for offline call summaries/analytics; for DeepSeek quality in real time, use R1 distills on Groq |

### Self-hosted

- **SGLang** — top pick for voice agents: RadixAttention prefix caching reuses the long repeated system prompt + tool schemas across turns (~112ms TTFT, ~29% higher throughput than vLLM on prefix-heavy traffic).
- **vLLM** — the safe default, widest support (~120ms TTFT p50).
- TensorRT-LLM — best raw numbers, heavy ops. llama.cpp/Ollama — dev only.

Model sweet spot: **27–32B class** (Qwen3-32B, Gemma 27B) — near-top of open models on tool-calling (BFCL), strong multilingual, fits **one H100 80GB** (FP8) or a 48GB GPU quantized. 70B (Llama 3.3) = higher ceiling, 2× H100. One H100 at ~$1.50–3/hr ≈ $1,100–2,200/mo serves dozens of concurrent calls.

### Tool-calling + Arabic (BOL-specific)

- **Qwen3-32B is the single-model answer**: near-top of open models on BFCL tool-calling *and* best general open model for Arabic (119 languages).
- Llama 3.3 70B: highest tool-calling ceiling (~97% well-formed) but mediocre Arabic.
- Arabic-native specialists to watch for fine-tuning: **Falcon-H1 Arabic** (TII), **Jais 30B** (Apache-2.0), ALLaM, Fanar 2.0 — win on dialect/culture, lag on tool calling.
- Live rankings: [BFCL leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html).

### Cost reality

A call generates ~300–2,000 tokens/min → **~$0.001–0.003/min on Groq 70B**. The LLM is **<5% of per-minute cost** — optimize it for latency, not price. STT (~$0.008), TTS (~$0.02–0.04), telephony (~$0.005–0.01) dominate; self-hosting *speech* is where real savings live.

**Recommendation**: MVP on Groq (Qwen3-32B primary, Cerebras fallback). At scale, self-host Qwen3-32B on SGLang (1× H100, FP8, prefix caching), fine-tune on real BOL transcripts — the decisive long-term advantage of open weights.

---

## 3. Speech — TTS and STT

### On "Omni voice"

- **OmniVoice (k2-fsa)** exists: Apache-2.0 TTS (Mar 2026), 600+ languages incl. Arabic, 40x real-time — but documents batch inference, not chunked streaming, and voice design skews Chinese/English. **Watch it; don't build on it yet** for sub-300ms telephony. ([repo](https://github.com/k2-fsa/OmniVoice))
- Omni *models* (Qwen-Omni, MiniCPM-o, Moshi): see end-to-end section below.

### TTS comparison (commercially usable, streaming-relevant)

| Model | License | TTFA / streaming | Arabic | Notes |
|---|---|---|---|---|
| **Chatterbox Multilingual v3 (0.5B)** | MIT | ~75–200ms | **Yes** (23 langs) | Beat ElevenLabs in blind tests (~64–65% preference); 10-sec zero-shot cloning; one 4090/L40S. **← primary** |
| **Kokoro (82M)** | Apache-2.0 | Near-instant; runs on CPU | No | Cheapest concurrency per dollar. **← fallback** |
| **Orpheus 3B** | Apache-2.0 | ~130–180ms (vLLM, A100/H100) | English-centric | Most expressive English. |
| CosyVoice2-0.5B | Apache-2.0 | ~150ms first packet | Some | Solid multilingual alt. |
| Kyutai TTS | Permissive | Streams *text in* from LLM (~350ms) | EN/FR only | Clever architecture. |
| Piper | MIT | Real-time on a Pi | Yes | Telephony-acceptable, robotic. |
| XTTS v2 / Fish Speech / F5-TTS | **Non-commercial** | — | — | **Blocked** for a commercial platform. |

### STT comparison

| Model | License | Streaming | Arabic | Notes |
|---|---|---|---|---|
| **faster-whisper large-v3-turbo** | MIT | VAD-chunked pseudo-streaming (~0.5–1s) | **Yes, best open** | ~6GB int8 on L4/A10. **← primary (Arabic/multilingual)** |
| **NVIDIA Parakeet TDT 0.6B-v3** | CC-BY-4.0 | True streaming, very low latency | No (v3); RNNT multilingual variant lists Arabic (verify WER) | Hundreds of concurrent calls/GPU. **← primary (English-first)** |
| Moonshine v2 | MIT | Yes, ~107ms, CPU/edge | No | English edge fallback. |
| Vosk | Apache-2.0 | True streaming, tiny | Yes (mediocre WER) | Zero-GPU option. |

### End-to-end speech-to-speech (Moshi, Qwen-Omni, MiniCPM-o)

Not production-ready for a controllable multi-tenant calling platform in 2026 — weak steering for business flows, DIY telephony integration, licensing caveats. The **cascade** (streaming ASR → LLM → streaming TTS) remains the production architecture; Kyutai's Unmute is the pattern to copy. Achievable total: **~300–500ms voice-to-voice** (ASR ~30–80ms + LLM first token ~150–300ms + TTS first audio ~75–180ms).

One L40S/A10-class GPU hosts both TTS and STT for dozens of concurrent calls; scale horizontally per ~50–100 calls.

---

## Final recommendations

| Layer | MVP | Scale |
|---|---|---|
| Telephony | LiveKit Cloud + Telnyx SIP trunk | Self-hosted LiveKit + livekit/sip |
| Orchestration | LiveKit Agents (Python) | Same (code unchanged) |
| LLM | Qwen3-32B on Groq | Qwen3-32B on SGLang, 1× H100, fine-tuned |
| STT | faster-whisper large-v3-turbo (self-hosted from day one — cheap) | Same, more GPUs; Parakeet for EN |
| TTS | Chatterbox Multilingual v3 (self-hosted) | Same; watch k2-fsa OmniVoice for Arabic breadth |
| Carrier | Telnyx | Telnyx + second carrier (DIDWW/VoIP.ms) |

All-in cost trajectory: ~$0.05/min (MVP, mixed hosted) → **~$0.01–0.02/min** fully self-hosted, vs $0.10–0.30/min on Vapi/Retell/Bland and Twilio-based stacks.
