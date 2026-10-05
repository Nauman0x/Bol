"""Per-call latency capture and aggregation.

Fed one item.metrics dict at a time by worker/agent.py's
conversation_item_added handler — the same MetricsReport livekit-agents
already attaches to every ChatMessage
(livekit.agents.llm.chat_context.MetricsReport). This module doesn't measure
anything itself; it extracts the keys that matter, keeps every provider
(Groq/Fish/Chatterbox TTS, any STT, any LLM) on equal footing since the
report shape is the same regardless of which plugin produced it, and turns
the per-turn samples into call-level statistics using only the stdlib.
"""

import statistics
from typing import Any, Literal

# e2e_latency is the number that matters most — user stopped speaking to
# agent began responding. The rest is the breakdown that explains *why* a
# given turn was slow: which stage (STT / LLM / TTS / playback) ate the time.
_USER_KEYS = ("transcription_delay", "end_of_turn_delay", "on_user_turn_completed_delay")
_ASSISTANT_KEYS = (
    "e2e_latency",
    "llm_node_ttft",
    "llm_node_ttfs",
    "tts_node_ttfb",
    "playback_latency",
    "llm_node_tps",
)
_METADATA_KEYS = ("stt_metadata", "llm_metadata", "tts_metadata")


def _stage_stats(samples: list[float]) -> dict[str, float]:
    stats = {
        "count": len(samples),
        "avg": round(statistics.fmean(samples), 3),
        "min": round(min(samples), 3),
        "max": round(max(samples), 3),
    }
    if len(samples) >= 2:
        quantiles = statistics.quantiles(samples, n=100, method="inclusive")
        stats["p50"] = round(quantiles[49], 3)
        stats["p95"] = round(quantiles[94], 3)
    else:
        # statistics.quantiles needs >=2 points; a single sample IS both
        # its own p50 and p95.
        stats["p50"] = stats["p95"] = stats["max"]
    return stats


_InterruptionKind = Literal["true", "false", "resumed", "acked", "connector"]


class LatencyCollector:
    def __init__(self) -> None:
        self._stage_samples: dict[str, list[float]] = {}
        self._providers: dict[str, str] = {}
        self._interruption_counts: dict[str, int] = {}
        self._interruption_style: str | None = None
        self._interruption_mode_effective: str | None = None

    def record_interruption(self, kind: _InterruptionKind) -> None:
        """Called from worker/agent.py's session-event handlers (see
        worker/interruption.py) — "true" for an interruption that actually
        cut the agent off (ChatMessage.interrupted), "false"/"resumed" from
        the agent_false_interruption event, "acked" when a barge-in
        acknowledgment was spoken, "connector" when a false-interruption
        resume used a spoken connector instead of the framework's silent
        mid-word resume."""
        self._interruption_counts[kind] = self._interruption_counts.get(kind, 0) + 1

    def set_interruption_config(self, style: str, mode_effective: str) -> None:
        """Recorded once per call so the summary is self-describing — which
        preset and which detection mode (vad/adaptive, post-downgrade) were
        actually in effect, without needing to cross-reference the agent's
        config as of call time."""
        self._interruption_style = style
        self._interruption_mode_effective = mode_effective

    def record_turn(self, role: str, metrics: dict[str, Any]) -> dict[str, float]:
        """Extract this turn's relevant keys, record them for later
        aggregation, and return the rounded dict the caller writes into
        call_events.payload.timings (transport unchanged from before)."""
        keys = _USER_KEYS if role == "user" else _ASSISTANT_KEYS
        timings: dict[str, float] = {}
        for key in keys:
            if key in metrics:
                value = round(metrics[key], 3)
                timings[key] = value
                self._stage_samples.setdefault(key, []).append(value)

        for meta_key in _METADATA_KEYS:
            meta = metrics.get(meta_key)
            if not meta:
                continue
            stage = meta_key.removesuffix("_metadata")
            if "model_name" in meta:
                self._providers[f"{stage}_model"] = meta["model_name"]
            if "model_provider" in meta:
                self._providers[f"{stage}_provider"] = meta["model_provider"]

        return timings

    def summary(self) -> dict[str, Any] | None:
        """None when no assistant turn ever completed AND no interruption
        was ever recorded (e.g. hangup before the agent said anything) —
        nothing meaningful to store. A call where the caller barged into
        the greeting and then hung up has interruption data but no
        e2e_latency sample, and that's still worth keeping."""
        has_latency_data = "e2e_latency" in self._stage_samples
        if not has_latency_data and not self._interruption_counts:
            return None
        summary: dict[str, Any] = {
            "turn_count": len(self._stage_samples.get("e2e_latency", [])),
            "stages": {
                key: _stage_stats(samples) for key, samples in self._stage_samples.items()
            },
            "providers": dict(self._providers),
        }
        if self._interruption_counts or self._interruption_style is not None:
            summary["interruptions"] = {
                "true": self._interruption_counts.get("true", 0),
                "false": self._interruption_counts.get("false", 0),
                "resumed": self._interruption_counts.get("resumed", 0),
                "acked": self._interruption_counts.get("acked", 0),
                "connector": self._interruption_counts.get("connector", 0),
                "style": self._interruption_style,
                "mode_effective": self._interruption_mode_effective,
            }
        return summary

    def headline_ms(self) -> tuple[int | None, int | None]:
        """(avg_ms, p95_ms) for e2e_latency — the two scalar columns the API
        stores alongside the full JSON breakdown, so simple queries (e.g.
        "calls over 2s") don't need JSON extraction, which isn't portable
        between SQLite (tests) and Postgres (prod) anyway."""
        samples = self._stage_samples.get("e2e_latency")
        if not samples:
            return None, None
        stats = _stage_stats(samples)
        return round(stats["avg"] * 1000), round(stats["p95"] * 1000)
