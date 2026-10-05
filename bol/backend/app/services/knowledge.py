"""Local, self-hosted knowledge-base embeddings for the `lookup_knowledge`
agent tool (worker/tools.py). Uses fastembed's ONNX runtime — no external
API/key, consistent with BOL's self-host-first positioning.

Search is brute-force cosine similarity over a JSON-stored float array per
chunk (app/models/knowledge.py), not a pgvector index — an org's knowledge
base is expected to be tens to low-hundreds of chunks, and comparing a
query vector against a few hundred 384-dim vectors in Python is well under
a live call's latency budget. Revisit with a real ANN index only if that
assumption stops holding.
"""

import asyncio
import uuid
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk

# Multilingual (50+ languages) and compact enough to run CPU-only inside the
# API process — BOL supports agents in any language (app/schemas/agent.py),
# not just the two this model's name might suggest.
_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100
_TOP_K = 4
_MIN_SIMILARITY = 0.3

_model: Any = None


def _get_model() -> Any:
    # Lazy singleton — importing/instantiating fastembed's TextEmbedding
    # loads the ONNX model from disk (or downloads it once, cached
    # thereafter), which is far too slow to redo per request. Synchronous
    # and CPU/IO-bound — never call this directly from an async context,
    # only via warm_model()/embed_texts() below, which offload it to a
    # thread so it can't block the event loop for every other in-flight
    # request (including live-call traffic hitting /internal/*).
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=_MODEL_NAME)
    return _model


async def warm_model() -> None:
    """Loads the model on API startup (see app/main.py's lifespan) so the
    first real request doesn't pay for it — on a fresh container this can
    be a multi-second local load (or a one-time download). Best-effort:
    a failure here just means the first knowledge-base request pays the
    cost instead, not that the API fails to start."""
    await asyncio.to_thread(_get_model)


def chunk_text(text: str) -> list[str]:
    """Fixed-size sliding window over characters, not tokens or sentences —
    simple and language-agnostic (matters for Arabic, where word-boundary
    splitting needs RTL-aware handling this doesn't bother with)."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    while start < len(text):
        chunk = text[start : start + _CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vec.tolist() for vec in _get_model().embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """CPU-bound ONNX inference — offloaded to a thread so a large document
    (hundreds of chunks) or a live-call knowledge lookup never stalls the
    event loop for every other in-flight request."""
    return await asyncio.to_thread(_embed_texts_sync, texts)


def _rank_chunks_sync(
    query_vector: list[float], chunks: list[KnowledgeChunk], top_k: int
) -> list[str]:
    # Vectorized cosine similarity over all chunks at once (numpy, already
    # a fastembed dependency) rather than a pure-Python loop per chunk —
    # both for speed and because this also runs off the event loop (see
    # search() below), so the actual latency matters less than not holding
    # up other requests, but there's no reason to leave it slow either.
    query = np.asarray(query_vector)
    matrix = np.asarray([chunk.embedding for chunk in chunks])
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = np.where(norms > 0, matrix @ query / norms, 0.0)

    ranked = sorted(zip(chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [chunk.text for chunk, score in ranked[:top_k] if score >= _MIN_SIMILARITY]


async def search(
    db: AsyncSession, org_id: uuid.UUID, query: str, top_k: int = _TOP_K
) -> list[str]:
    result = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.org_id == org_id))
    all_chunks = list(result.scalars().all())
    if not all_chunks:
        return []

    query_vectors = await embed_texts([query])
    return await asyncio.to_thread(_rank_chunks_sync, query_vectors[0], all_chunks, top_k)
