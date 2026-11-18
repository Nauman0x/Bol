# urdu-llm

BOL Urdu LLM (FYP-I). Plan: `PLAN.md`. Phase 1 results: `report/bakeoff/README.md`. Sources and licences: `data/SOURCES.md`.

## Setup (WSL2, Ubuntu 24.04, RTX 5070)
- `bash setup_wsl.sh serve|train` builds `.venv-serve` / `.venv-train` (pip only, no sudo/nvcc). Versions: `versions-<what>.txt`.
- `bash scripts/get_llamacpp.sh` fetches the prebuilt llama.cpp CUDA build. `scripts/curl_dl.sh` is the resumable GGUF downloader.
- `scripts/run_local.sh <gguf> <alias> <tag> [flags]` runs warm and cold latency plus probe generation; `scripts/run_groq.sh` does the hosted reference.
- `scripts/bench_models.py` has `fertility`, `latency`, `probe-gen`, `probe-export`, `probe-score`. Judging is done in-session (no API key).

## Skills used
architecture (ADR), system-design, testing-strategy, debug, documentation, huggingface-local-models, huggingface-datasets: copied from the vetted skill sets into `~/.claude/skills` after reading each SKILL.md. Review skills: code-review, simplify.
