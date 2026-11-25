set -e
cd ~/urdu-llm/llama.cpp
rm -rf conv src.tgz
curl -sfL -o src.tgz https://github.com/ggml-org/llama.cpp/archive/refs/tags/b12283.tar.gz
mkdir conv && tar xzf src.tgz -C conv --strip-components=1 --wildcards '*/convert_*.py' '*/conversion/*' '*/gguf-py/*' '*/requirements/*'
ls conv
