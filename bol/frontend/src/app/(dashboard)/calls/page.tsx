"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import { useAgents, useCalls, useCreateOutboundCall } from "@/lib/hooks";
import type { CallDirection, CallStatus } from "@/lib/types";

const STATUS_VARIANT: Record<CallStatus, "default" | "secondary" | "destructive" | "outline"> = {
  queued: "secondary",
  ringing: "secondary",
  in_progress: "default",
  completed: "outline",
  failed: "destructive",
  no_answer: "destructive",
  busy: "destructive",
};

const DIRECTION_LABELS: Record<string, string> = {
  all: "All directions",
  inbound: "Inbound",
  outbound: "Outbound",
  test: "Test",
};

const STATUS_LABELS: Record<string, string> = {
  all: "All statuses",
  queued: "Queued",
  ringing: "Ringing",
  in_progress: "In progress",
  completed: "Completed",
  failed: "Failed",
  no_answer: "No answer",
  busy: "Busy",
};

function formatDuration(sec: number | null): string {
  if (sec === null) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatLatency(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

export default function CallsPage() {
  const [direction, setDirection] = useState<CallDirection | "all">("all");
  const [status, setStatus] = useState<CallStatus | "all">("all");
  const { data: calls, isLoading } = useCalls({
    direction: direction === "all" ? undefined : direction,
    status: status === "all" ? undefined : status,
  });
  const { data: agents } = useAgents();
  const createOutbound = useCreateOutboundCall();

  const [dialAgentId, setDialAgentId] = useState("");
  const [dialNumber, setDialNumber] = useState("");
  const [dialing, setDialing] = useState(false);

  const agentName = (id: string) => agents?.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  async function handleOutboundCall(e: React.FormEvent) {
    e.preventDefault();
    setDialing(true);
    try {
      await createOutbound.mutateAsync({ agent_id: dialAgentId, to_number: dialNumber });
      toast.success("Call dispatched");
      setDialNumber("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to place call");
    } finally {
      setDialing(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Calls</h1>
        <p className="text-muted-foreground">Call history and live status.</p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleOutboundCall} className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Agent</label>
              <Select value={dialAgentId} onValueChange={(v) => setDialAgentId(v ?? "")}>
                <SelectTrigger className="w-48">
                  <SelectValue>
                    {(value) =>
                      value ? (agents?.find((a) => a.id === value)?.name ?? "Select agent") : "Select agent"
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {agents?.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Number</label>
              <Input
                placeholder="+15551234567"
                value={dialNumber}
                onChange={(e) => setDialNumber(e.target.value)}
                className="w-48"
                required
              />
            </div>
            <Button type="submit" disabled={dialing || !dialAgentId}>
              {dialing ? "Calling…" : "Make outbound call"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Select
          value={direction}
          onValueChange={(v) => setDirection((v as CallDirection | null) ?? "all")}
        >
          <SelectTrigger className="w-40">
            <SelectValue>
              {(value) => DIRECTION_LABELS[String(value ?? "all")] ?? "All directions"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {Object.entries(DIRECTION_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={(v) => setStatus((v as CallStatus | null) ?? "all")}>
          <SelectTrigger className="w-40">
            <SelectValue>
              {(value) => STATUS_LABELS[String(value ?? "all")] ?? "All statuses"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Direction</TableHead>
              <TableHead>Number</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Avg latency</TableHead>
              <TableHead>Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {calls?.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  No calls yet.
                </TableCell>
              </TableRow>
            )}
            {calls?.map((call) => (
              <TableRow key={call.id} className="cursor-pointer">
                <TableCell className="capitalize">{call.direction}</TableCell>
                <TableCell>
                  <Link href={`/calls/${call.id}`} className="hover:underline">
                    {call.direction === "outbound" ? call.to_number : call.from_number}
                  </Link>
                </TableCell>
                <TableCell>{agentName(call.agent_id)}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[call.status]} className="capitalize">
                    {call.status.replace("_", " ")}
                  </Badge>
                </TableCell>
                <TableCell>{formatDuration(call.duration_sec)}</TableCell>
                <TableCell className="tabular-nums">{formatLatency(call.avg_latency_ms)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(call.created_at).toLocaleString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
