#!/usr/bin/env bash
# resume_dl.sh : (re)start the Qwen3 + Qalb GGUF downloads detached; salvage a stale .incomplete if hf restarted from zero.
cd "$(dirname "$0")/.."
for p in $(pgrep -f 'hf download'); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
sleep 2
D=models/qwen3/.cache/huggingface/download
big=$(ls -S $D/*.incomplete 2>/dev/null | head -1); small=$(ls -S $D/*.incomplete 2>/dev/null | tail -1)
if [ -n "$big" ] && [ "$big" != "$small" ]; then rm "$small"; mv "$big" "$small"; echo "salvaged $(du -h "$small" | cut -f1)"; fi
source .venv-serve/bin/activate; export HF_HUB_DISABLE_XET=1
setsid nohup bash -c 'hf download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf --local-dir models/qwen3 && hf download mradermacher/Qalb-1.0-8B-Instruct-GGUF Qalb-1.0-8B-Instruct.Q4_K_M.gguf --local-dir models/qalb && touch dl_done.flag' > dl_gguf3.log 2>&1 < /dev/null &
sleep 20; ls -la $D | grep incomplete | awk '{print $5}'
