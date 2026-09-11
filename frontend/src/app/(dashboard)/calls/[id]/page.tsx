"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Call, CallEvent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function isTranscript(event: CallEvent) {
  return event.type === "transcript_user" || event.type === "transcript_agent";
}

export default function CallDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const { data: call } = useQuery({
    queryKey: ["calls", id],
    queryFn: async () => (await api.get<Call>(`/calls/${id}`)).data,
  });

  const { data: events, isLoading } = useQuery({
    queryKey: ["calls", id, "events"],
    queryFn: async () => (await api.get<CallEvent[]>(`/calls/${id}/events`)).data,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Call transcript</h1>
        {call && <Badge variant="secondary">{call.status}</Badge>}
      </div>

      {isLoading && <p className="text-muted-foreground">Loading transcript...</p>}

      <div className="flex flex-col gap-3">
        {events
          ?.filter(isTranscript)
          .map((event) => {
            const isAgent = event.type === "transcript_agent";
            const text = (event.payload as { text?: string }).text ?? "";
            return (
              <div
                key={event.id}
                className={cn("flex flex-col gap-1", isAgent ? "items-start" : "items-end")}
              >
                <div
                  className={cn(
                    "max-w-md rounded-lg px-4 py-2 text-sm",
                    isAgent ? "bg-muted" : "bg-primary text-primary-foreground"
                  )}
                >
                  {text}
                </div>
                <span className="text-xs text-muted-foreground">
                  {isAgent ? "Agent" : "Caller"} - {new Date(event.ts).toLocaleTimeString()}
                </span>
              </div>
            );
          })}
        {events && events.filter(isTranscript).length === 0 && (
          <p className="text-muted-foreground">No transcript yet.</p>
        )}
      </div>
    </div>
  );
}
