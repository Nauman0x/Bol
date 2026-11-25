#!/usr/bin/env bash
# Convert models/lora-c1 (PEFT) to a GGUF LoRA for llama-server --lora. Run in WSL after scripts/fetch_conv.sh.
set -e
cd ~/urdu-llm
C=llama.cpp/conv
# config-only base so the converter does not read the bnb weights
mkdir -p models/qwen25-cfg
for f in config.json tokenizer.json tokenizer_config.json vocab.json merges.txt generation_config.json; do cp models/qwen25-bnb4/$f models/qwen25-cfg/; done
python3 - <<'PY'
import json
p = "models/qwen25-cfg/config.json"; c = json.load(open(p)); c.pop("quantization_config", None); json.dump(c, open(p, "w"), indent=1)
PY
source .venv-train/bin/activate
export PYTHONPATH=$C/gguf-py:$C
python $C/convert_lora_to_gguf.py --base models/qwen25-cfg --outtype f16 --outfile models/lora-c1/lora-c1-f16.gguf models/lora-c1
ls -la models/lora-c1
