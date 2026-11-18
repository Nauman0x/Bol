# ADR-001: Base model for the BOL Urdu LLM

**Status:** Proposed. Awaiting the Phase 1 decision-gate review. Not final.
**Date:** 2026-11-18

## Context
PLAN.md fixes a three-arm study; the C arms fine-tune one open base. Candidates: Qwen2.5-7B-Instruct, Qwen3-8B, Qalb-1.0-8B-Instruct. Constraints: RTX 5070 12 GB, TTFT p50 ≤ 80 ms, TTFS p50 ≤ 250 ms, ≥ 60 tok/s, VRAM ≤ ~9 GB, commercial use permitted. Evidence: `report/bakeoff/README.md`.

## Options
| Option | For | Against |
|---|---|---|
| Qwen2.5-7B | fastest TTFS (44 ms), 6.8 GB, Apache-2.0, quality tied with Qwen3 | ~3/5 prompt-only; Roman Urdu is weak |
| Qwen3-8B | quality tied, newer, 7.7 GB, Apache-2.0 | TTFS 2x slower, thinking mode must be disabled, longer replies |
| Qalb-8B | Urdu continued pretraining (~1.97B tokens per its card) | **not fairly tested**: third-party GGUF loops; Llama 3.1 licence conditions bind every adapter |

## Decision (proposed)
Qwen2.5-7B-Instruct as the C-arm base, **unless** a fair Qalb retry changes the picture. Quality does not separate the two Qwens, so latency and licence simplicity decide.

## Consequences
- Easier: smallest VRAM headroom pressure (room for LoRA training/serving), simple licence story.
- Harder: prompt-only quality is low, so the thesis depends on fine-tuning data (Phases 2-6).
- Revisit if: the Qalb retry scores clearly higher, or bf16 testing reverses the Qwen tie.

## Action items
1. User decision at the gate (including whether to retry Qalb).
2. Read full Qwen and Llama 3.1 licence texts (not yet read).
3. Build `.venv-train` and check bitsandbytes on sm_120.
