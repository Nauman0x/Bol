"use client";

import { Room, RoomEvent, Track } from "livekit-client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ApiError } from "@/lib/api";
import { useCall, useCallRecording, useHangupCall, useListenToCall } from "@/lib/hooks";
import type { CallAnalysis, LatencyStats, TurnTimings } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTIVE_STATUSES = new Set(["queued", "ringing", "in_progress"]);

// Pipeline order, not alphabetical — this is the order these stages
// actually happen in a turn, so a reader scanning top-to-bottom sees the
// call's shape instead of a shuffled list.
const STAGE_LABELS: Record<string, string> = {
  transcription_delay: "STT (transcription)",
  end_of_turn_delay: "Turn detection",
  on_user_turn_completed_delay: "Turn-completed hook",
  llm_node_ttft: "LLM (first token)",
  llm_node_ttfs: "LLM → TTS handoff",
  tts_node_ttfb: "TTS (first audio byte)",
  playback_latency: "Playback",
  e2e_latency: "Total (speech end → response start)",
  llm_node_tps: "LLM tokens/sec",
};
const STAGE_ORDER = Object.keys(STAGE_LABELS);

function formatMs(seconds: number): string {
  const ms = seconds * 1000;
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function LatencyCard({ stats }: { stats: LatencyStats }) {
  const e2e = stats.stages.e2e_latency;
  const stageEntries = STAGE_ORDER.filter((key) => key in stats.stages && key !== "e2e_latency");
  const maxAvg = Math.max(...stageEntries.map((key) => stats.stages[key].avg), 0.001);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Latency</CardTitle>
        <CardDescription>
          {stats.turn_count} turn{stats.turn_count === 1 ? "" : "s"}
          {Object.keys(stats.providers).length > 0 && (
            <>
              {" · "}
              {Object.entries(stats.providers)
                .filter(([key]) => key.endsWith("_model"))
                .map(([key, value]) => `${key.replace("_model", "")}: ${value}`)
                .join(" · ")}
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {e2e && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(["avg", "p50", "p95", "max"] as const).map((key) => (
              <div key={key} className="flex flex-col gap-0.5 rounded-md border p-3">
                <span className="text-xs text-muted-foreground uppercase">{key}</span>
                <span className="text-lg font-semibold tabular-nums">{formatMs(e2e[key])}</span>
              </div>
            ))}
          </div>
        )}

        {stageEntries.length > 0 && (
          <div className="flex flex-col gap-2">
            {stageEntries.map((key) => {
              const stage = stats.stages[key];
              return (
                <div key={key} className="flex items-center gap-3 text-sm">
                  <span className="w-48 shrink-0 text-muted-foreground">{STAGE_LABELS[key]}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${(stage.avg / maxAvg) * 100}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right tabular-nums">
                    {formatMs(stage.avg)}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {stats.interruptions && (
          <div className="flex flex-col gap-2 border-t pt-3">
            <span className="text-xs text-muted-foreground uppercase">Interruptions</span>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <span>
                <span className="font-semibold tabular-nums">{stats.interruptions.true}</span>{" "}
                genuine
              </span>
              <span>
                <span className="font-semibold tabular-nums">{stats.interruptions.false}</span>{" "}
                false
              </span>
              {stats.interruptions.acked > 0 && (
                <span>
                  <span className="font-semibold tabular-nums">{stats.interruptions.acked}</span>{" "}
                  acknowledged
                </span>
              )}
              {stats.interruptions.connector > 0 && (
                <span>
                  <span className="font-semibold tabular-nums">
                    {stats.interruptions.connector}
                  </span>{" "}
                  resumed with connector
                </span>
              )}
              {stats.interruptions.style && (
                <Badge variant="outline" className="capitalize">
                  {stats.interruptions.style}
                  {stats.interruptions.mode_effective === "adaptive" ? " · adaptive" : ""}
                </Badge>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AnalysisCard({ analysis }: { analysis: CallAnalysis }) {
  const extractedEntries = Object.entries(analysis.extracted ?? {});
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Analysis</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          {analysis.outcome && (
            <Badge variant="outline" className="capitalize">
              {analysis.outcome}
            </Badge>
          )}
          {analysis.sentiment && (
            <Badge variant="outline" className="capitalize">
              {analysis.sentiment}
            </Badge>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {analysis.summary && <p className="text-sm">{analysis.summary}</p>}
        {extractedEntries.length > 0 && (
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {extractedEntries.map(([key, value]) => (
              <div key={key} className="flex flex-col gap-0.5 rounded-md border p-2 text-sm">
                <dt className="text-xs text-muted-foreground">{key}</dt>
                <dd>{value === null ? "—" : String(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function ListenInButton({ callId }: { callId: string }) {
  const listen = useListenToCall();
  const [listening, setListening] = useState(false);
  const roomRef = useRef<Room | null>(null);
  const audioContainerRef = useRef<HTMLDivElement>(null);

  async function start() {
    try {
      const session = await listen.mutateAsync(callId);
      const room = new Room();
      roomRef.current = room;
      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) {
          audioContainerRef.current?.appendChild(track.attach());
        }
      });
      room.on(RoomEvent.Disconnected, () => setListening(false));
      await room.connect(session.livekit_url, session.token);
      setListening(true);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not listen in");
    }
  }

  async function stop() {
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setListening(false);
  }

  useEffect(() => {
    return () => {
      roomRef.current?.disconnect();
    };
  }, []);

  return (
    <>
      <div ref={audioContainerRef} className="hidden" />
      {listening ? (
        <Button variant="secondary" size="sm" onClick={stop}>
          Stop listening
        </Button>
      ) : (
        <Button variant="secondary" size="sm" onClick={start} disabled={listen.isPending}>
          {listen.isPending ? "Connecting…" : "Listen in"}
        </Button>
      )}
    </>
  );
}

function TurnTimingChip({ isUser, timings }: { isUser: boolean; timings: TurnTimings }) {
  const value = isUser ? timings.transcription_delay : timings.e2e_latency;
  if (value === undefined) return null;
  return (
    <span className="mt-1 text-[10px] text-muted-foreground tabular-nums">
      {isUser ? "transcribed in " : "responded in "}
      {formatMs(value)}
    </span>
  );
}

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: call, isLoading } = useCall(id);
  const hangup = useHangupCall();
  const { data: recording } = useCallRecording(call?.id, call?.has_recording ?? false);

  async function handleHangup() {
    if (!call) return;
    try {
      await hangup.mutateAsync(call.id);
      toast.success("Call ended");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to hang up");
    }
  }

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!call) return <p className="text-muted-foreground">Call not found.</p>;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Button variant="ghost" size="sm" className="w-fit" onClick={() => router.push("/calls")}>
        ← Back to calls
      </Button>

      <Card>
        <CardHeader>
          <CardTitle className="capitalize">
            {call.direction} call — {call.direction === "outbound" ? call.to_number : call.from_number}
          </CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-x-2">
            <span>{new Date(call.created_at).toLocaleString()}</span>
            {call.duration_sec !== null && <span>· {call.duration_sec}s</span>}
            {call.end_reason && <span>· {call.end_reason}</span>}
            {call.transport && (
              <Badge variant="outline" className="capitalize">
                {call.transport}
              </Badge>
            )}
            {call.tts_provider && <Badge variant="outline">TTS: {call.tts_provider}</Badge>}
            {call.llm_model && <Badge variant="outline">LLM: {call.llm_model}</Badge>}
            {call.cost_estimate !== null && (
              <Badge variant="outline">${call.cost_estimate.toFixed(4)}</Badge>
            )}
          </CardDescription>
          <CardAction className="flex items-center gap-2">
            <Badge className="capitalize">{call.status.replace("_", " ")}</Badge>
            {ACTIVE_STATUSES.has(call.status) && <ListenInButton callId={call.id} />}
            {ACTIVE_STATUSES.has(call.status) && (
              <Button variant="destructive" size="sm" onClick={handleHangup}>
                Hang up
              </Button>
            )}
          </CardAction>
        </CardHeader>
      </Card>

      {call.analysis && <AnalysisCard analysis={call.analysis} />}

      {call.latency_stats && <LatencyCard stats={call.latency_stats} />}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Transcript</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {call.events.length === 0 && (
            <p className="text-sm text-muted-foreground">No events yet.</p>
          )}
          {call.events.map((event) => {
            if (event.type === "transcript_user" || event.type === "transcript_agent") {
              const isUser = event.type === "transcript_user";
              return (
                <div
                  key={event.id}
                  className={cn("flex flex-col", isUser ? "items-end" : "items-start")}
                >
                  <div
                    dir="auto"
                    className={cn(
                      "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                      isUser ? "bg-primary text-primary-foreground" : "bg-muted",
                    )}
                  >
                    {String(event.payload.text ?? "")}
                  </div>
                  {event.payload.timings && (
                    <TurnTimingChip isUser={isUser} timings={event.payload.timings} />
                  )}
                </div>
              );
            }
            if (event.type === "tool_call" || event.type === "tool_result") {
              return (
                <div key={event.id} className="flex justify-center">
                  <span className="rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground">
                    {event.type === "tool_call" ? "→" : "←"} {String(event.payload.name ?? "tool")}
                  </span>
                </div>
              );
            }
            return (
              <div key={event.id} className="flex justify-center">
                <span className="text-xs text-muted-foreground">
                  {event.type}: {JSON.stringify(event.payload)}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {call.has_recording && recording && (
        <>
          <Separator />
          <div className="flex items-center gap-3">
            <audio controls src={recording.url} className="w-full" />
            <Button
              variant="secondary"
              size="sm"
              nativeButton={false}
              render={
                <a href={`${recording.url}&download=true`} download={`call-${call.id}.ogg`} />
              }
            >
              Download
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
