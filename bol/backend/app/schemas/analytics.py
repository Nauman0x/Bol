from pydantic import BaseModel


class CallsByDay(BaseModel):
    date: str
    count: int


class AnalyticsSummary(BaseModel):
    total_calls: int
    total_minutes: float
    answer_rate: float
    avg_duration_sec: float
    calls_by_day: list[CallsByDay]


class LatencyGroupStat(BaseModel):
    key: str
    call_count: int
    avg_latency_ms: float
    avg_p95_latency_ms: float


class LatencyOverall(BaseModel):
    call_count: int
    avg_latency_ms: float | None
    avg_p95_latency_ms: float | None
    min_latency_ms: int | None
    max_latency_ms: int | None


class LatencyAnalytics(BaseModel):
    """avg_latency_ms/avg_p95_latency_ms are the mean of each call's own
    avg/p95 e2e_latency (worker/latency.py:LatencyCollector.headline_ms())
    — an average of per-call summaries, not a true percentile recomputed
    over every individual turn (those raw samples aren't stored outside
    each call's own latency_stats JSON blob). Good enough to compare
    providers/transports against each other; not a statistically exact p95
    across all turns platform-wide."""

    overall: LatencyOverall
    by_transport: list[LatencyGroupStat]
    by_tts_provider: list[LatencyGroupStat]
    by_llm_model: list[LatencyGroupStat]
