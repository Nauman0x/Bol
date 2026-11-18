# Phase 1 bake-off: base-model table

Hardware: RTX 5070 12 GB (WSL2). All local rows: **Q4_K_M GGUF, llama.cpp b12283, full GPU offload, 4 parallel slots**, temperature 0, ~520-token system prompt, 40 requests per cell. Groq row is hosted (network included), 20 requests.
Raw data: `latency.jsonl`, `probe_scores.json`, `fertility.json`. Probe = 30 synthetic Urdish turns (20 restaurant, 10 clinic), judged **in-session, blind and shuffled** (model identity in a key file I did not open while scoring). One judge, one pass: treat differences under ~0.5 as noise.

| | Qwen2.5-7B | Qwen3-8B (no-think) | Qalb-8B (Llama-3 template)* | Groq Qwen3.8-27B (A') |
|---|---|---|---|---|
| Fertility Roman / Urdu (tok/word) | 1.75 / 3.09 | 1.75 / 3.09 | 1.70 / 3.00 | n/a |
| TTFT p50, 1 stream warm (target ≤80 ms) | 21 ms | 22 ms | 19 ms | 146 ms |
| TTFS p50, 1 stream warm (target ≤250 ms) | **44 ms** | 100 ms | 76 ms | 211 ms |
| TTFS p50, 4 streams, cold prefix | 255 ms | 455 ms | 414 ms | n/a |
| Decode p50, 1 stream (target ≥60 tok/s) | 112 | 105 | 107 | 262 |
| Decode p50, 4 streams cold | 35 | 34 | 43 | n/a |
| VRAM (target ≤ ~9 GB) | 6.8 GB | 7.7 GB | 7.5 GB | n/a |
| Probe overall (1-5) [95% CI] | 2.98 [2.67, 3.28] | 3.01 [2.76, 3.26] | **2.12** [1.80, 2.47] | **4.57** [4.35, 4.76] |
| understood / register / tone / faithful | 2.9 / 2.9 / 3.1 / 3.0 | 3.0 / 2.8 / 3.1 / 3.2 | 2.3 / 1.4 / 2.3 / 2.5 | 4.6 / 4.7 / 4.7 / 4.3 |
| Replies ≤35 words | 100% | 100% | 87% | 100% |
| Licence | Apache-2.0 | Apache-2.0 | Llama 3.1 Community (conditions) | n/a |

\* **Qalb retry (round 2).** First run used llama.cpp's ChatML fallback (the GGUF has no template) and looped (overall 1.40, kept in `probe_scores_round1.json`). The model card documents a **Llama-3 chat format** and sampling at temperature 0.1 with repetition penalty 1.1. Re-run with that template (`scripts/llama3.jinja`, `<|eot_id|>` stop), still greedy and without repetition penalty: **2.12**, still below both Qwens. Failure mode: it often answers in **English** (register 1.4), invents prices, and sometimes echoes the caller. The retry was judged blind in a 60-item mix with Qwen2.5 as an anchor (Qwen2.5 rescored 2.96 vs 2.98, so the judging is consistent). Still untested for Qalb: repetition penalty and the original bf16 weights; the third-party Q4 quant remains a possible small confound.

## Findings
- **Qwen2.5 vs Qwen3: quality is a tie** (CIs overlap); Qwen2.5 is faster to first speakable clause and lighter. Both are poor in absolute terms (about 3/5 prompt-only), with garbled Roman Urdu, echoing the caller, invented facts (a medical dose, a promised 10% discount, "peanuts not used"). That is the gap fine-tuning is meant to close.
- **Hosted Qwen3.8-27B is far better on quality (4.6)** but its TTFT is ~7x the local one (network hop, as LATENCY.md found). It is a different, much larger model than the plan's "Groq Qwen3": the old id `qwen/qwen3-32b` no longer exists on this key.
- **Qalb, run properly, still trails the Qwens at prompt-only** (2.1 vs 3.0). Urdu continued-pretraining did not buy Roman-Urdu phone-agent behaviour.
- Local latency targets are met warm by every model. Cold prefix with 4 concurrent streams breaks TTFS ≤250 ms for Qwen3 and Qalb, only just for Qwen2.5 (255 ms): prompt caching of the system prompt is essential.
- **Fertility does not separate the models**, as expected (Qalb is ~3% better).

## Caveats (stated, not hidden)
1. Q4_K_M for all, because the link runs at ~2 MB/s (user decision). bf16/FP8/vLLM was not tested; absolute quality at higher precision may differ.
2. Judge is the same model family that wrote the test set and the plan; single pass, n=30 per model.
3. Greedy decoding; no repetition penalty. May unfairly hurt Qalb and small models.
4. Latency measured with a local client over loopback; Groq includes the WSL network path.
5. vLLM works on this card (env verified) but did not serve a model: llama.cpp was used for all candidates.
