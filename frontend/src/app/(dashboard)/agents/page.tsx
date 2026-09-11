"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const DEFAULT_CONFIG = {
  system_prompt: "You are a helpful assistant for this business.",
  greeting: "Hello, how can I help you today?",
  language: "auto" as const,
  voice_id: "arista",
  llm_model: "qwen/qwen3-32b",
  temperature: 0.7,
  max_call_duration_sec: 300,
};

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  const { data: agents, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: async () => (await api.get<Agent[]>("/agents")).data,
  });

  const createAgent = useMutation({
    mutationFn: async () => (await api.post<Agent>("/agents", { name, config: DEFAULT_CONFIG })).data,
    onSuccess: (agent) => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      setOpen(false);
      setName("");
      router.push(`/agents/${agent.id}`);
    },
    onError: () => toast.error("Could not create agent"),
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Agents</h1>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button>New agent</Button>} />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create agent</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Label htmlFor="agent-name">Name</Label>
              <Input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <DialogFooter>
              <Button
                onClick={() => createAgent.mutate()}
                disabled={!name || createAgent.isPending}
              >
                {createAgent.isPending ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading agents...</p>}

      {agents && agents.length === 0 && (
        <p className="text-muted-foreground">No agents yet. Create one to get started.</p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {agents?.map((agent) => (
          <Link key={agent.id} href={`/agents/${agent.id}`}>
            <Card className="transition hover:border-foreground/30">
              <CardHeader>
                <CardTitle className="text-base">{agent.name}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {agent.config.language.toUpperCase()} - {agent.config.voice_id}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
