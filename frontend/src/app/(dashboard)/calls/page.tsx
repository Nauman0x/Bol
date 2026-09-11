"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Agent, Call } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function statusVariant(status: Call["status"]) {
  if (status === "completed") return "default" as const;
  if (status === "in_progress") return "secondary" as const;
  return "destructive" as const;
}

export default function CallsPage() {
  const { data: calls, isLoading } = useQuery({
    queryKey: ["calls"],
    queryFn: async () => (await api.get<Call[]>("/calls")).data,
  });

  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: async () => (await api.get<Agent[]>("/agents")).data,
  });

  const agentName = (agentId: string) => agents?.find((a) => a.id === agentId)?.name ?? agentId;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Calls</h1>

      {isLoading && <p className="text-muted-foreground">Loading calls...</p>}
      {calls && calls.length === 0 && <p className="text-muted-foreground">No calls yet.</p>}

      {calls && calls.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Started</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {calls.map((call) => (
              <TableRow key={call.id} className="cursor-pointer">
                <TableCell>
                  <Link href={`/calls/${call.id}`} className="block">
                    {agentName(call.agent_id)}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(call.status)}>{call.status}</Badge>
                </TableCell>
                <TableCell>{call.duration_sec != null ? `${call.duration_sec}s` : "-"}</TableCell>
                <TableCell>{new Date(call.started_at).toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
