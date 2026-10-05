# API service (FastAPI). For the worker process see Dockerfile.worker —
# they share this same source tree but install different dependency
# extras and have different entrypoints.
FROM python:3.12-slim

# onnxruntime (pulled in by fastembed, for the knowledge-base tool —
# app/services/knowledge.py) dlopens libgomp.so.1 at import time. Not
# present in the slim base image; without it the first knowledge-base
# request (or the startup warmup in app/main.py's lifespan) fails with
# "ImportError: libgomp.so.1: cannot open shared object file".
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Unbuffered stdout/stderr — otherwise Railway (and most log collectors)
# can lose or badly delay output, which is exactly what you don't want
# while debugging a first deploy.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# Source is copied before `pip install .` (not split into a
# deps-only-then-source layering) because this is a non-editable install —
# setuptools needs app/ and worker/ to actually exist to build the
# distribution; installing `-e .` before COPY . . (the previous approach)
# only appeared to work because editable installs fall back to a loose
# .pth-file mode, which is fragile and version-dependent.
COPY . .
RUN uv pip install --system .

# Bakes the knowledge-base embedding model into the image so a fresh
# container's first request doesn't pay for a runtime download (needs
# egress and takes tens of seconds) — see app/services/knowledge.py.
RUN python -c "from fastembed import TextEmbedding; \
TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

RUN chmod +x docker-entrypoint.sh

CMD ["./docker-entrypoint.sh"]
