#!/usr/bin/env bash
# One-time setup inside WSL2 Ubuntu on the training PC. Run from the urdu-tts
# folder, which should live in the Linux filesystem (~/urdu-tts), not /mnt/c.
#
#   bash setup_wsl.sh
set -euo pipefail

nvidia-smi >/dev/null || { echo "GPU not visible in WSL. Update the Windows NVIDIA driver, then 'wsl --shutdown' and retry." >&2; exit 1; }

chmod +x scripts/*.sh

sudo apt update
sudo apt install -y build-essential cmake ninja-build git ffmpeg tmux python3-venv python3-dev

[ -d piper1-gpl ] || git clone https://github.com/OHF-Voice/piper1-gpl.git
cd piper1-gpl
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[train]'
./build_monotonic_align.sh
cd ..

python3 -m pip install datasets soundfile librosa soxr pyloudnorm transformers jiwer tensorboard pytest

python3 -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available()); assert torch.cuda.is_available()"
python3 -m pytest tests -q

# Stock Urdu voice (baseline to beat) and its training checkpoint (fine-tune base).
hf download rhasspy/piper-voices --include "ur/ur_PK/fasih/medium/*" --local-dir voices
hf download rhasspy/piper-checkpoints --repo-type dataset --include "ur/ur_PK/fasih/medium/*" --local-dir checkpoints

export PYTHONPATH=scripts
python3 scripts/synth.py --model voices/ur/ur_PK/fasih/medium/ur_PK-fasih-medium.onnx \
    --text-file sentences/listen.txt --out samples/baseline

echo
echo "Setup done. Listen to samples/baseline/*.wav, then follow README.md from step 3."
echo "In each new shell:  source piper1-gpl/.venv/bin/activate && export PYTHONPATH=scripts"
