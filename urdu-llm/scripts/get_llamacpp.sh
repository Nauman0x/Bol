#!/usr/bin/env bash
# Fetch the official prebuilt llama.cpp CUDA 12.8 build (covers sm_120) into ./llama.cpp.
# Needed because nvcc is not installed and sudo is unavailable, so we cannot build from source.
# Binary comes from the ggml-org release page; pin the tag so runs are reproducible.
set -euo pipefail
TAG="${LLAMACPP_TAG:-b12283}"
BASE="https://github.com/ggml-org/llama.cpp/releases/download/$TAG"
mkdir -p llama.cpp && cd llama.cpp
for f in "llama-$TAG-bin-ubuntu-cuda-12.8-x64.tar.gz" "cudart-llama-$TAG-bin-ubuntu-cuda-12.8-x64.tar.gz"; do
  [ -f "$f" ] || curl -fSL --retry 5 -O "$BASE/$f"
  tar xzf "$f"
done
find . -name llama-server -o -name llama-bench
