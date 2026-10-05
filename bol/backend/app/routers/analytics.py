from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.call import Call, CallStatus
from app.schemas.analytics import (
    AnalyticsSummary,
    CallsByDay,
    LatencyAnalytics,
    LatencyGroupStat,
    LatencyOverall,
)
from app.security import CurrentUser

router = APIRouter(prefix="/analytics", tags=["analytics"])

_ANSWERED_STATUSES = (CallStatus.in_progress, CallStatus.completed)
_LOOKBACK_DAYS = 30


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> AnalyticsSummary:
    since = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
    org_filter = (Call.org_id == current_user.org_id, Call.created_at >= since)

    # Aggregated in SQL rather than loading every call row into Python —
    # this endpoint used to `select(Call)` with no LIMIT and sum/average in
    # a loop, which doesn't scale past a small number of calls per org.
    # SQL's AVG/SUM already skip NULL duration_sec rows, matching the old
    # Python-side "if c.duration_sec is not None" filter exactly.
    stats_result = await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Call.duration_sec), 0),
            func.coalesce(func.avg(Call.duration_sec), 0),
        ).where(*org_filter)
    )
    total_calls, total_duration_sec, avg_duration_sec = stats_result.one()

    answered_result = await db.execute(
        select(func.count()).where(*org_filter, Call.status.in_(_ANSWERED_STATUSES))
    )
    answered = answered_result.scalar_one()

    by_day_result = await db.execute(
        select(func.date(Call.created_at), func.count())
        .where(*org_filter)
        .group_by(func.date(Call.created_at))
        .order_by(func.date(Call.created_at))
    )
    calls_by_day = [CallsByDay(date=str(day), count=count) for day, count in by_day_result.all()]

    return AnalyticsSummary(
        total_calls=total_calls,
        total_minutes=round(total_duration_sec / 60, 2),
        answer_rate=round(answered / total_calls, 4) if total_calls else 0.0,
        avg_duration_sec=round(float(avg_duration_sec), 1),
        calls_by_day=calls_by_day,
    )


@router.get("/latency", response_model=LatencyAnalytics)
async def get_latency_analytics(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> LatencyAnalytics:
    """Compares latency across transport (telephony/webrtc) and TTS/LLM
    provider — the numbers worker/latency.py's LatencyCollector already
    computes per call, aggregated here across calls instead of per-turn."""
    since = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
    base_filter = (
        Call.org_id == current_user.org_id,
        Call.created_at >= since,
        Call.avg_latency_ms.is_not(None),
    )

    overall_result = await db.execute(
        select(
            func.count(),
            func.avg(Call.avg_latency_ms),
            func.avg(Call.p95_latency_ms),
            func.min(Call.avg_latency_ms),
            func.max(Call.avg_latency_ms),
        ).where(*base_filter)
    )
    count, avg_ms, avg_p95_ms, min_ms, max_ms = overall_result.one()
    overall = LatencyOverall(
        call_count=count,
        avg_latency_ms=round(avg_ms, 1) if avg_ms is not None else None,
        avg_p95_latency_ms=round(avg_p95_ms, 1) if avg_p95_ms is not None else None,
        min_latency_ms=min_ms,
        max_latency_ms=max_ms,
    )

    async def _group_by(column: ColumnElement) -> list[LatencyGroupStat]:
        result = await db.execute(
            select(
                column,
                func.count(),
                func.avg(Call.avg_latency_ms),
                func.avg(Call.p95_latency_ms),
            )
            .where(*base_filter, column.is_not(None))
            .group_by(column)
            .order_by(func.avg(Call.avg_latency_ms))
        )
        return [
            LatencyGroupStat(
                key=key,
                call_count=cnt,
                avg_latency_ms=round(avg, 1),
                avg_p95_latency_ms=round(p95, 1),
            )
            for key, cnt, avg, p95 in result.all()
        ]

    return LatencyAnalytics(
        overall=overall,
        by_transport=await _group_by(Call.transport),
        by_tts_provider=await _group_by(Call.tts_provider),
        by_llm_model=await _group_by(Call.llm_model),
    )
