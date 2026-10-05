"""Post-call LLM analysis: a summary/outcome/sentiment plus optional
per-agent structured extraction, computed once after a call reaches a
terminal state. Best-effort — any failure here must never affect whether
the call itself is recorded as complete (see app/routers/internal.py).
"""

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("BOL.analysis")

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
# Deliberately not settings.llm_model (the per-call conversational model) —
# analysis runs after the call ends, off the latency-sensitive path, so
# quality matters more than speed here, the opposite tradeoff from live
# turn-taking. The 8B model was noticeably weaker at non-English summaries
# and extraction; 70B is the flagship Groq offers and still runs well under
# _TIMEOUT_SEC for a single analysis call (docs/RESEARCH.md's own tool-
# calling comparison also ranks it highest, at ~97% well-formed).
_ANALYSIS_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT_SEC = 15.0


def _build_transcript(events: list[dict[str, Any]]) -> str:
    lines = []
    for event in events:
        text = event.get("payload", {}).get("text")
        if not text:
            continue
        if event["type"] == "transcript_user":
            lines.append(f"Caller: {text}")
        elif event["type"] == "transcript_agent":
            lines.append(f"Agent: {text}")
    return "\n".join(lines)


async def analyze_call(
    events: list[dict[str, Any]], analysis_schema: dict[str, str]
) -> dict[str, Any] | None:
    """events: [{"type": ..., "payload": {...}}, ...] in chronological order.
    analysis_schema: agent-defined extra fields to extract, {field_name:
    description}. Returns None (never raises) if analysis can't run or fails
    — a missing GROQ_API_KEY, an empty transcript, an API error, or a
    non-JSON response are all treated the same way: no analysis this time."""
    if not settings.groq_api_key:
        return None
    transcript = _build_transcript(events)
    if not transcript.strip():
        return None

    schema_instruction = ""
    if analysis_schema:
        fields = ", ".join(f'"{k}": {v!r}' for k, v in analysis_schema.items())
        schema_instruction = (
            f"\n\nAlso include an \"extracted\" object with these fields, using null for "
            f"any that weren't mentioned: {{{fields}}}"
        )
    prompt = (
        "You are analyzing a completed phone call transcript. Respond with a JSON object "
        'containing: "summary" (one or two sentences, written in the same language as the '
        'transcript below — do not translate it), "outcome" (one of: resolved, escalated, '
        'voicemail, no_answer, abandoned, other — always in English, these are matched by '
        'code), "sentiment" (positive, neutral, negative — always in English)'
        f'.{schema_instruction}\n\nTranscript:\n{transcript}'
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(
                _GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={
                    "model": _ANALYSIS_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError):
        logger.exception("Post-call analysis failed")
        return None
