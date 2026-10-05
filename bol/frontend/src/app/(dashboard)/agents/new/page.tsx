"use client";

import { AgentForm } from "@/components/agent-form";

export default function NewAgentPage() {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New agent</h1>
        <p className="text-muted-foreground">
          You can test it from your browser once it&apos;s created.
        </p>
      </div>
      <AgentForm mode="create" />
    </div>
  );
}
