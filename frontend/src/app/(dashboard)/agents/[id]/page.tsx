"use client";

import { use, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Agent, AgentConfig, Language, Voice } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TestCallDialog } from "@/components/test-call-dialog";
import { toast } from "sonner";

export default function AgentBuilderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const router = useRouter();
  const [testCallOpen, setTestCallOpen] = useState(false);

  const { data: agent, isLoading } = useQuery({
    queryKey: ["agents", id],
    queryFn: async () => (await api.get<Agent>(`/agents/${id}`)).data,
  });

  const { data: voices } = useQuery({
    queryKey: ["voices"],
    queryFn: async () => (await api.get<Voice[]>("/voices")).data,
  });

  const [name, setName] = useState("");
  const [config, setConfig] = useState<AgentConfig | null>(null);

  useEffect(() => {
    if (agent) {
      setName(agent.name);
      setConfig(agent.config);
    }
  }, [agent]);

  const save = useMutation({
    mutationFn: async () => {
      if (!config) return;
      return (await api.patch<Agent>(`/agents/${id}`, { name, config })).data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent saved");
    },
    onError: () => toast.error("Could not save agent"),
  });

  const remove = useMutation({
    mutationFn: async () => api.delete(`/agents/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      router.push("/agents");
    },
    onError: () => toast.error("Could not delete agent"),
  });

  if (isLoading || !config) {
    return <p className="text-muted-foreground">Loading agent...</p>;
  }

  function updateConfig<K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Edit agent</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setTestCallOpen(true)}>
            Test call
          </Button>
          <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Delete
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Basics</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="greeting">Greeting</Label>
            <Textarea
              id="greeting"
              value={config.greeting}
              onChange={(e) => updateConfig("greeting", e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="prompt">System prompt</Label>
            <Textarea
              id="prompt"
              rows={6}
              value={config.system_prompt}
              onChange={(e) => updateConfig("system_prompt", e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Voice & model</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label>Language</Label>
            <Select
              value={config.language}
              onValueChange={(value) => updateConfig("language", value as Language)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto-detect</SelectItem>
                <SelectItem value="en">English</SelectItem>
                <SelectItem value="ur">Urdu</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Voice</Label>
            <Select
              value={config.voice_id}
              onValueChange={(value) => updateConfig("voice_id", value ?? "")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {voices?.map((voice) => (
                  <SelectItem key={voice.id} value={voice.id}>
                    {voice.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="model">LLM model</Label>
            <Input
              id="model"
              value={config.llm_model}
              onChange={(e) => updateConfig("llm_model", e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label>Temperature: {config.temperature.toFixed(1)}</Label>
            <Slider
              value={[config.temperature]}
              min={0}
              max={2}
              step={0.1}
              onValueChange={(value) => updateConfig("temperature", Array.isArray(value) ? value[0] : value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="duration">Max call duration (seconds)</Label>
            <Input
              id="duration"
              type="number"
              min={30}
              max={3600}
              value={config.max_call_duration_sec}
              onChange={(e) => updateConfig("max_call_duration_sec", Number(e.target.value))}
            />
          </div>
        </CardContent>
      </Card>

      <TestCallDialog agentId={id} open={testCallOpen} onOpenChange={setTestCallOpen} />
    </div>
  );
}
