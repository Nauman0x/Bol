"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { languageLabel } from "@/components/agent-form";
import { ApiError } from "@/lib/api";
import { useAgents, useDeleteAgent } from "@/lib/hooks";

export default function AgentsPage() {
  const { data: agents, isLoading } = useAgents();
  const deleteAgent = useDeleteAgent();
  const router = useRouter();

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete agent "${name}"? This cannot be undone.`)) return;
    try {
      await deleteAgent.mutateAsync(id);
      toast.success("Agent deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete agent");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
          <p className="text-muted-foreground">Voice agents that answer or make calls.</p>
        </div>
        <Button onClick={() => router.push("/agents/new")}>New agent</Button>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading…</p>}

      {agents && agents.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No agents yet. Create your first one to get started.
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {agents?.map((agent) => (
          <Card key={agent.id} className="cursor-pointer hover:border-primary/40">
            <CardHeader onClick={() => router.push(`/agents/${agent.id}`)}>
              <CardTitle className="flex items-center gap-2">
                {agent.name}
                {!agent.is_active && <Badge variant="secondary">Inactive</Badge>}
              </CardTitle>
              <CardDescription dir="auto" className="line-clamp-2">
                {agent.config.greeting || agent.config.system_prompt}
              </CardDescription>
              <CardAction>
                <Badge variant="outline">{languageLabel(agent.config.language)}</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex items-center justify-between">
              <Link
                href={`/agents/${agent.id}`}
                className="text-sm text-primary underline-offset-4 hover:underline"
              >
                Edit
              </Link>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(agent.id, agent.name);
                }}
              >
                Delete
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
