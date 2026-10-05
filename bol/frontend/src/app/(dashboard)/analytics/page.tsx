"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAnalytics, useLatencyAnalytics } from "@/lib/hooks";
import type { LatencyGroupStat } from "@/lib/types";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function LatencyGroupTable({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: LatencyGroupStat[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Not enough data yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="capitalize">{title}</TableHead>
                <TableHead>Calls</TableHead>
                <TableHead>Avg latency</TableHead>
                <TableHead>Avg p95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.key}>
                  <TableCell className="font-medium">{row.key}</TableCell>
                  <TableCell>{row.call_count}</TableCell>
                  <TableCell className="tabular-nums">{formatMs(row.avg_latency_ms)}</TableCell>
                  <TableCell className="tabular-nums">
                    {formatMs(row.avg_p95_latency_ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const { data, isLoading } = useAnalytics();
  const { data: latency } = useLatencyAnalytics();

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!data) return <p className="text-muted-foreground">No analytics available.</p>;

  const maxCount = Math.max(1, ...data.calls_by_day.map((d) => d.count));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">Last 30 days.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total calls" value={String(data.total_calls)} />
        <StatCard label="Total minutes" value={data.total_minutes.toFixed(1)} />
        <StatCard label="Answer rate" value={`${(data.answer_rate * 100).toFixed(0)}%`} />
        <StatCard label="Avg duration" value={`${data.avg_duration_sec.toFixed(0)}s`} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Calls per day</CardTitle>
        </CardHeader>
        <CardContent>
          {data.calls_by_day.length === 0 ? (
            <p className="text-sm text-muted-foreground">No calls in the last 30 days.</p>
          ) : (
            <div className="flex h-48 items-end gap-1">
              {data.calls_by_day.map((day) => (
                <div key={day.date} className="flex flex-1 flex-col items-center gap-1">
                  <div
                    className="w-full rounded-t bg-primary transition-all"
                    style={{ height: `${(day.count / maxCount) * 100}%` }}
                    title={`${day.date}: ${day.count} call${day.count === 1 ? "" : "s"}`}
                  />
                  <span className="text-[10px] text-muted-foreground">
                    {day.date.slice(5)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {latency && (
        <>
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Latency</h2>
            <p className="text-muted-foreground">
              How fast the agent responds — end to end, and broken down by transport and
              provider so you can tell what a provider swap actually changed.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Calls with latency data"
              value={String(latency.overall.call_count)}
            />
            <StatCard
              label="Avg latency"
              value={
                latency.overall.avg_latency_ms !== null
                  ? formatMs(latency.overall.avg_latency_ms)
                  : "—"
              }
            />
            <StatCard
              label="Avg p95"
              value={
                latency.overall.avg_p95_latency_ms !== null
                  ? formatMs(latency.overall.avg_p95_latency_ms)
                  : "—"
              }
            />
            <StatCard
              label="Range"
              value={
                latency.overall.min_latency_ms !== null && latency.overall.max_latency_ms !== null
                  ? `${formatMs(latency.overall.min_latency_ms)} – ${formatMs(latency.overall.max_latency_ms)}`
                  : "—"
              }
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <LatencyGroupTable
              title="Transport"
              description="Telephony vs. browser test calls."
              rows={latency.by_transport}
            />
            <LatencyGroupTable
              title="TTS provider"
              description="Groq vs. Fish vs. Chatterbox."
              rows={latency.by_tts_provider}
            />
            <LatencyGroupTable
              title="LLM model"
              description="Per model id in use."
              rows={latency.by_llm_model}
            />
          </div>
        </>
      )}
    </div>
  );
}
