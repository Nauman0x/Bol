"use client";

import { useParams } from "next/navigation";

import { AgentForm } from "@/components/agent-form";
import { TestCallPanel } from "@/components/test-call-panel";
import { useAgent } from "@/lib/hooks";

export default function EditAgentPage() {
  const { id } = useParams<{ id: string }>();
  const { data: agent, isLoading } = useAgent(id);

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!agent) return <p className="text-muted-foreground">Agent not found.</p>;

  return (
    <div className="flex max-w-5xl flex-col gap-6 lg:flex-row lg:items-start">
      <div className="flex-1">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">{agent.name}</h1>
          <p className="text-muted-foreground">Edit agent configuration</p>
        </div>
        <AgentForm mode="edit" agent={agent} />
      </div>
      <div className="w-full lg:w-80 lg:shrink-0">
        <TestCallPanel agentId={agent.id} ttsProvider={agent.config.tts_provider} />
      </div>
    </div>
  );
}
