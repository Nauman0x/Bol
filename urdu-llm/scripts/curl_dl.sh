#!/usr/bin/env bash
# curl_dl.sh : resumable (curl -C -) download of the Qwen3 and Qalb GGUFs. hf download restarts from zero after every
# interruption (new .incomplete name each run); curl can resume the partial file in place. Verifies Qwen3 sha256.
cd "$(dirname "$0")/.."
for p in $(pgrep -f 'hf download'); do kill "$p" 2>/dev/null; done; sleep 2
mkdir -p models/qwen3 models/qalb
Q3=models/qwen3/Qwen3-8B-Q4_K_M.gguf
big=$(ls -S models/qwen3/.cache/huggingface/download/*.incomplete 2>/dev/null | head -1)
[ -n "$big" ] && [ ! -f "$Q3" ] && mv "$big" "$Q3"
until curl -fL -C - --retry 20 --retry-delay 5 -o "$Q3" https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf; do sleep 5; done
echo "qwen3 sha256: $(sha256sum "$Q3" | cut -d' ' -f1)  (expect d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785)"
QB=models/qalb/Qalb-1.0-8B-Instruct.Q4_K_M.gguf
until curl -fL -C - --retry 20 --retry-delay 5 -o "$QB" https://huggingface.co/mradermacher/Qalb-1.0-8B-Instruct-GGUF/resolve/main/Qalb-1.0-8B-Instruct.Q4_K_M.gguf; do sleep 5; done
touch dl_done.flag; echo ALL_DONE
