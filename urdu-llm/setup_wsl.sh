#!/usr/bin/env bash
# One-time setup inside WSL2 Ubuntu on the training PC (RTX 5070 12 GB, Blackwell sm_120).
# Run from the urdu-llm folder, which should live in the Linux filesystem (~/urdu-llm), not /mnt/c.
#
#   bash setup_wsl.sh serve    # venv for vLLM serving + benchmarks   (.venv-serve)
#   bash setup_wsl.sh train    # venv for the QLoRA stack              (.venv-train)
#
# Two venvs on purpose: vLLM pins its own torch/transformers, the training stack wants
# recent ones. No sudo is used (the account needs a password); everything is pip-only.
set -euo pipefail

nvidia-smi >/dev/null || { echo "GPU not visible in WSL. Update the Windows NVIDIA driver, 'wsl --shutdown', retry." >&2; exit 1; }

what="${1:-serve}"
python3 -m venv ".venv-$what"
source ".venv-$what/bin/activate"
python3 -m pip install --upgrade pip uv

case "$what" in
  serve)
    # vLLM brings the torch build it was compiled against; check it supports sm_120 below.
    uv pip install vllm
    uv pip install transformers huggingface_hub sentencepiece numpy scipy pandas httpx aiohttp openai pytest
    ;;
  train)
    # torch wheel with CUDA >= 12.8 is required for sm_120; cu130 is what urdu-tts ended up on.
    uv pip install torch --index-url https://download.pytorch.org/whl/cu130
    uv pip install transformers peft trl bitsandbytes accelerate datasets huggingface_hub scipy pandas pytest
    ;;
  *) echo "usage: $0 serve|train" >&2; exit 2 ;;
esac

python3 - <<'EOF'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
assert torch.cuda.is_available()
print("device", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
print("arch list", torch.cuda.get_arch_list())
x = torch.randn(1024, 1024, device="cuda", dtype=torch.bfloat16)
print("bf16 matmul ok:", float((x @ x).float().abs().mean()) > 0)
EOF
pip freeze > "versions-$what.txt"
echo "Done. Activate with: source .venv-$what/bin/activate   (exact versions in versions-$what.txt)"
