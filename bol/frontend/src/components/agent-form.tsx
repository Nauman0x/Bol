"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  useAmbienceClips,
  useCreateAgent,
  useInterruptionPresets,
  useTools,
  useTtsProviders,
  useUpdateAgent,
  useUploadAmbienceClip,
  useVoices,
} from "@/lib/hooks";
import type {
  Agent,
  AgentConfig,
  AgentLanguage,
  AgentTool,
  BuiltinTool,
  ToolRef,
  TtsProviderId,
} from "@/lib/types";

interface AgentFormProps {
  mode: "create" | "edit";
  agent?: Agent;
}

// Common languages offered in the picker — not an exhaustive/closed list.
// The backend accepts any 2-3 letter ISO-639 code (app/schemas/agent.py);
// an agent whose stored language isn't in this list still works, it just
// renders its raw code instead of a friendly label (see languageLabel()).
export const LANGUAGE_OPTIONS: { code: AgentLanguage; label: string }[] = [
  { code: "auto", label: "Auto-detect" },
  { code: "en", label: "English" },
  { code: "es", label: "Spanish — Español" },
  { code: "fr", label: "French — Français" },
  { code: "de", label: "German — Deutsch" },
  { code: "ar", label: "Arabic — العربية" },
  { code: "hi", label: "Hindi — हिन्दी" },
  { code: "ur", label: "Urdu — اردو" },
  { code: "zh", label: "Chinese — 中文" },
  { code: "ja", label: "Japanese — 日本語" },
  { code: "ko", label: "Korean — 한국어" },
  { code: "pt", label: "Portuguese — Português" },
  { code: "ru", label: "Russian — Русский" },
  { code: "it", label: "Italian — Italiano" },
  { code: "tr", label: "Turkish — Türkçe" },
  { code: "nl", label: "Dutch — Nederlands" },
  { code: "pl", label: "Polish — Polski" },
  { code: "id", label: "Indonesian — Bahasa Indonesia" },
  { code: "vi", label: "Vietnamese — Tiếng Việt" },
  { code: "th", label: "Thai — ไทย" },
  { code: "fa", label: "Persian — فارسی" },
  { code: "he", label: "Hebrew — עברית" },
  { code: "sv", label: "Swedish — Svenska" },
  { code: "uk", label: "Ukrainian — Українська" },
  { code: "el", label: "Greek — Ελληνικά" },
  { code: "cs", label: "Czech — Čeština" },
  { code: "ro", label: "Romanian — Română" },
  { code: "bn", label: "Bengali — বাংলা" },
  { code: "ta", label: "Tamil — தமிழ்" },
  { code: "sw", label: "Swahili — Kiswahili" },
  { code: "ms", label: "Malay — Bahasa Melayu" },
];

export function languageLabel(code: string): string {
  return LANGUAGE_OPTIONS.find((o) => o.code === code)?.label ?? code;
}

const BUILTIN_AMBIENCE_OPTIONS: { value: string; label: string }[] = [
  { value: "office", label: "Office" },
  { value: "city", label: "City" },
  { value: "forest", label: "Forest" },
  { value: "crowded_room", label: "Crowded room" },
  { value: "hold_music", label: "Hold music" },
];

const DEFAULT_CONFIG: AgentConfig = {
  system_prompt: "",
  greeting: "",
  language: "en",
  voice_id: "default",
  tts_provider: null,
  llm_model: "qwen/qwen3.6-27b",
  temperature: 0.7,
  max_call_duration_sec: 600,
  interruption_enabled: true,
  interruption_style: "balanced",
  interruption_mode: "vad",
  interruption_min_duration: 0.3,
  interruption_min_words: 0,
  false_interruption_timeout: 2.0,
  ack_on_interrupt: false,
  resume_style: "instant",
  ambience: null,
  ambience_volume: 0.2,
  thinking_sound: false,
  greeting_mode: "agent_first",
  filler_phrases: false,
  boosted_keywords: [],
  analysis_schema: {},
};

export function AgentForm({ mode, agent }: AgentFormProps) {
  const router = useRouter();
  const { data: ttsProviders } = useTtsProviders();
  const { data: interruptionPresetsData } = useInterruptionPresets();
  const interruptionPresets = interruptionPresetsData?.presets ?? [];
  const adaptiveSupported = interruptionPresetsData?.adaptive_supported ?? false;
  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent(agent?.id ?? "");

  const [name, setName] = useState(agent?.name ?? "");
  // Spread over DEFAULT_CONFIG (not a plain ??) so an agent saved before
  // these fields existed — its stored config JSON simply won't have them —
  // still gets sane defaults instead of undefined.
  const [config, setConfig] = useState<AgentConfig>({
    ...DEFAULT_CONFIG,
    ...(agent?.config ?? {}),
  });
  const [tools, setTools] = useState<AgentTool[]>(agent?.tools ?? []);
  const [isActive, setIsActive] = useState(agent?.is_active ?? true);
  const [saving, setSaving] = useState(false);

  const { data: voices } = useVoices(config.tts_provider ?? undefined);
  const { data: ambienceClips } = useAmbienceClips();
  const uploadAmbienceClip = useUploadAmbienceClip();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Runs on provider switch (and on first load): if the currently-selected
  // voice isn't in the new provider's list, fall back to that provider's
  // first available voice rather than silently keeping a voice_id that
  // belongs to a different provider.
  useEffect(() => {
    if (!voices || voices.length === 0) return;
    if (voices.some((v) => v.id === config.voice_id)) return;
    updateConfig("voice_id", voices[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices]);

  function updateConfig<K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) {
    setConfig((c) => ({ ...c, [key]: value }));
  }

  function toggleToolRef(toolId: string, enabled: boolean) {
    setTools((t) => {
      const existing = t.find(
        (tool): tool is ToolRef => tool.type === "tool_ref" && tool.tool_id === toolId,
      );
      if (existing) {
        return t.map((tool): AgentTool =>
          tool.type === "tool_ref" && tool.tool_id === toolId ? { ...tool, enabled } : tool,
        );
      }
      return [...t, { type: "tool_ref", tool_id: toolId, enabled } satisfies ToolRef];
    });
  }

  function toggleBuiltin(
    type: "end_call" | "transfer_call" | "send_dtmf" | "lookup_knowledge",
    enabled: boolean,
    toolConfig: Record<string, unknown> = {},
  ) {
    setTools((t) => {
      const existing = t.find((tool) => tool.type === type);
      if (existing) {
        return t.map((tool): AgentTool =>
          tool.type === type ? { type, enabled, config: toolConfig } : tool,
        );
      }
      return [...t, { type, enabled, config: toolConfig } satisfies BuiltinTool];
    });
  }

  const transferTool = tools.find((t): t is BuiltinTool => t.type === "transfer_call");
  const endCallTool = tools.find((t): t is BuiltinTool => t.type === "end_call");
  const dtmfTool = tools.find((t): t is BuiltinTool => t.type === "send_dtmf");
  const knowledgeTool = tools.find((t): t is BuiltinTool => t.type === "lookup_knowledge");

  const { data: orgTools } = useTools();
  // Only present on an agent saved before the tools migration and never
  // resaved since — the editor here never produces a new "webhook" entry,
  // it's shown read-only as a nudge to recreate it as a reusable Tool.
  const legacyWebhookTools = tools.filter((t): t is Extract<AgentTool, { type: "webhook" }> =>
    t.type === "webhook",
  );

  const [analysisSchemaText, setAnalysisSchemaText] = useState(() =>
    JSON.stringify(config.analysis_schema, null, 2),
  );
  const [analysisSchemaError, setAnalysisSchemaError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      if (mode === "create") {
        const created = await createAgent.mutateAsync({ name, config, tools, is_active: isActive });
        toast.success("Agent created");
        router.push(`/agents/${created.id}`);
      } else {
        await updateAgent.mutateAsync({ name, config, tools, is_active: isActive });
        toast.success("Agent saved");
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save agent");
    } finally {
      setSaving(false);
    }
  }

  // Chatterbox voices are self-hosted names with no reliable per-voice
  // language metadata (unlike groq/fish, which report real languages per
  // voice) — filtering those by language would just hide everything.
  const languageMatchedVoices = voices?.filter(
    (v) =>
      v.provider === "chatterbox" ||
      config.language === "auto" ||
      v.languages.includes(config.language),
  );
  // No voice tagged for the chosen language (e.g. this provider just
  // doesn't have one yet) — show everything instead of an empty,
  // unusable picker, with a hint explaining why.
  const noLanguageMatch =
    config.language !== "auto" &&
    (voices?.length ?? 0) > 0 &&
    (languageMatchedVoices?.length ?? 0) === 0;
  const filteredVoices = noLanguageMatch ? voices : languageMatchedVoices;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="name">Agent name</Label>
          <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="language">Language</Label>
          <Select
            value={config.language}
            onValueChange={(v) => updateConfig("language", (v as AgentLanguage | null) ?? "en")}
          >
            <SelectTrigger id="language" className="w-full">
              <SelectValue>{(value) => languageLabel((value as string) ?? "en")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {LANGUAGE_OPTIONS.map((option) => (
                <SelectItem key={option.code} value={option.code}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="system_prompt">System prompt</Label>
        <Textarea
          id="system_prompt"
          dir="auto"
          rows={8}
          value={config.system_prompt}
          onChange={(e) => updateConfig("system_prompt", e.target.value)}
          placeholder="You are a helpful receptionist for..."
          required
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="greeting">Greeting (spoken first, on connect)</Label>
        <Textarea
          id="greeting"
          dir="auto"
          rows={2}
          value={config.greeting}
          onChange={(e) => updateConfig("greeting", e.target.value)}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="tts_provider">TTS provider</Label>
          <Select
            value={config.tts_provider ?? "__platform_default__"}
            onValueChange={(v) =>
              updateConfig(
                "tts_provider",
                v === "__platform_default__" ? null : (v as TtsProviderId),
              )
            }
          >
            <SelectTrigger id="tts_provider" className="w-full">
              <SelectValue>
                {(value) =>
                  value === "__platform_default__" || !value
                    ? "Platform default"
                    : (ttsProviders?.find((p) => p.id === value)?.label ?? String(value))
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__platform_default__">Platform default</SelectItem>
              {(ttsProviders ?? []).map((provider) => (
                <SelectItem key={provider.id} value={provider.id} disabled={!provider.configured}>
                  {provider.label}
                  {!provider.configured ? " (not configured)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="voice_id">Voice</Label>
          <Select
            value={config.voice_id}
            onValueChange={(v) => updateConfig("voice_id", v ?? "default")}
          >
            <SelectTrigger id="voice_id" className="w-full">
              <SelectValue>
                {(value) => voices?.find((v) => v.id === value)?.label ?? String(value ?? "")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {(filteredVoices ?? []).map((voice) => (
                <SelectItem key={voice.id} value={voice.id}>
                  {voice.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {noLanguageMatch && (
            <p className="text-xs text-muted-foreground">
              No voice tagged for {languageLabel(config.language)} on this provider — showing all.
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="llm_model">LLM model</Label>
          <Input
            id="llm_model"
            value={config.llm_model}
            onChange={(e) => updateConfig("llm_model", e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="temperature">Temperature</Label>
          <Input
            id="temperature"
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={config.temperature}
            onChange={(e) => updateConfig("temperature", Number(e.target.value))}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="max_call_duration_sec">Max call length (sec)</Label>
          <Input
            id="max_call_duration_sec"
            type="number"
            min={30}
            max={7200}
            value={config.max_call_duration_sec}
            onChange={(e) => updateConfig("max_call_duration_sec", Number(e.target.value))}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-8">
        <div className="flex items-center gap-2">
          <Switch
            id="interruption_enabled"
            checked={config.interruption_enabled}
            onCheckedChange={(v) => updateConfig("interruption_enabled", v)}
          />
          <Label htmlFor="interruption_enabled">Allow interruptions (barge-in)</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="filler_phrases"
            checked={config.filler_phrases}
            onCheckedChange={(v) => updateConfig("filler_phrases", v)}
          />
          <Label htmlFor="filler_phrases">Speak a filler while tools run</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="is_active" checked={isActive} onCheckedChange={setIsActive} />
          <Label htmlFor="is_active">Active</Label>
        </div>
      </div>

      {config.interruption_enabled && (
        <div className="flex flex-col gap-4 rounded-md border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="interruption_style">Interruption style</Label>
              <Select
                value={config.interruption_style}
                onValueChange={(v) =>
                  updateConfig(
                    "interruption_style",
                    (v as AgentConfig["interruption_style"] | null) ?? "balanced",
                  )
                }
              >
                <SelectTrigger id="interruption_style" className="w-full">
                  <SelectValue>
                    {(value) =>
                      value === "custom"
                        ? "Custom"
                        : (interruptionPresets.find((p) => p.id === value)?.label ??
                          String(value))
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {interruptionPresets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {preset.label}
                    </SelectItem>
                  ))}
                  <SelectItem value="custom">Custom</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {config.interruption_style === "custom"
                  ? "Set the exact thresholds below."
                  : interruptionPresets.find((p) => p.id === config.interruption_style)
                      ?.description}
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <Switch
                  id="interruption_mode"
                  checked={config.interruption_mode === "adaptive"}
                  disabled={!adaptiveSupported}
                  onCheckedChange={(v) => updateConfig("interruption_mode", v ? "adaptive" : "vad")}
                />
                <Label htmlFor="interruption_mode">Adaptive detection (ML)</Label>
              </div>
              <p className="text-xs text-muted-foreground">
                {adaptiveSupported
                  ? "Tells a real interruption apart from \"mhm\"/\"yeah\" — costs extra per call."
                  : interruptionPresetsData?.adaptive_unsupported_reason}
              </p>
            </div>
          </div>

          {config.interruption_style === "custom" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label htmlFor="interruption_min_duration">Min speech to interrupt (sec)</Label>
                <Input
                  id="interruption_min_duration"
                  type="number"
                  min={0.05}
                  max={3.0}
                  step={0.05}
                  value={config.interruption_min_duration}
                  onChange={(e) =>
                    updateConfig("interruption_min_duration", Number(e.target.value))
                  }
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="interruption_min_words">Min words to interrupt</Label>
                <Input
                  id="interruption_min_words"
                  type="number"
                  min={0}
                  max={10}
                  step={1}
                  value={config.interruption_min_words}
                  onChange={(e) => updateConfig("interruption_min_words", Number(e.target.value))}
                />
                <p className="text-xs text-muted-foreground">
                  Only takes effect with the streaming STT provider.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="false_interruption_timeout">Resume after (sec)</Label>
                <Input
                  id="false_interruption_timeout"
                  type="number"
                  min={0.3}
                  max={10.0}
                  step={0.1}
                  value={config.false_interruption_timeout}
                  onChange={(e) =>
                    updateConfig("false_interruption_timeout", Number(e.target.value))
                  }
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex items-center gap-2">
              <Switch
                id="ack_on_interrupt"
                checked={config.ack_on_interrupt}
                onCheckedChange={(v) => updateConfig("ack_on_interrupt", v)}
              />
              <Label htmlFor="ack_on_interrupt">
                Acknowledge interruptions (&ldquo;Go ahead.&rdquo;)
              </Label>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="resume_style">After a false interruption</Label>
              <Select
                value={config.resume_style}
                onValueChange={(v) =>
                  updateConfig("resume_style", (v as AgentConfig["resume_style"] | null) ?? "instant")
                }
              >
                <SelectTrigger id="resume_style" className="w-full">
                  <SelectValue>
                    {(value) =>
                      value === "connector"
                        ? "Resume with a spoken connector"
                        : "Resume instantly, mid-sentence"
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="instant">Resume instantly, mid-sentence</SelectItem>
                  <SelectItem value="connector">
                    Resume with a spoken connector (adds a full reply round-trip)
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="greeting_mode">Who speaks first</Label>
          <Select
            value={config.greeting_mode}
            onValueChange={(v) =>
              updateConfig(
                "greeting_mode",
                (v as AgentConfig["greeting_mode"] | null) ?? "agent_first",
              )
            }
          >
            <SelectTrigger id="greeting_mode" className="w-full">
              <SelectValue>
                {(value) =>
                  value === "wait_for_caller"
                    ? "Wait for caller to speak first"
                    : "Agent greets immediately"
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="agent_first">Agent greets immediately</SelectItem>
              <SelectItem value="wait_for_caller">Wait for caller to speak first</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="boosted_keywords">Boosted keywords (comma-separated)</Label>
          <Input
            id="boosted_keywords"
            placeholder="BOL, Telnyx, ..."
            value={config.boosted_keywords.join(", ")}
            onChange={(e) =>
              updateConfig(
                "boosted_keywords",
                e.target.value
                  .split(",")
                  .map((k) => k.trim())
                  .filter(Boolean),
              )
            }
          />
        </div>
      </div>

      <div className="flex flex-col gap-4 rounded-lg border p-4">
        <h3 className="font-medium">Background ambience</h3>
        <p className="text-sm text-muted-foreground">
          Plays on its own audio track alongside the agent&apos;s voice — doesn&apos;t affect
          response latency. 1.0 is each clip&apos;s normalized baseline volume; go above 1.0 for
          louder than that (may distort on the already-loud clips). Uploaded clips play at their
          own native volume, since there&apos;s nothing to normalize against.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="ambience">Ambience</Label>
            <Select
              value={config.ambience ?? "__none__"}
              onValueChange={(v) => updateConfig("ambience", v === "__none__" ? null : v)}
            >
              <SelectTrigger id="ambience" className="w-full">
                <SelectValue>
                  {(value) => {
                    if (value === "__none__" || !value) return "None";
                    if (typeof value === "string" && value.startsWith("custom:")) {
                      const clipId = value.slice("custom:".length);
                      return ambienceClips?.find((c) => c.id === clipId)?.name ?? "Custom clip";
                    }
                    return (
                      BUILTIN_AMBIENCE_OPTIONS.find((o) => o.value === value)?.label ??
                      String(value)
                    );
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">None</SelectItem>
                {BUILTIN_AMBIENCE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
                {(ambienceClips ?? []).map((clip) => (
                  <SelectItem key={clip.id} value={`custom:${clip.id}`}>
                    {clip.name} (uploaded)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ambience_volume">Ambience volume</Label>
            <Input
              id="ambience_volume"
              type="number"
              min={0}
              max={1.5}
              step={0.05}
              value={config.ambience_volume}
              onChange={(e) => updateConfig("ambience_volume", Number(e.target.value))}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Upload a clip</Label>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/ogg"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                try {
                  const clip = await uploadAmbienceClip.mutateAsync(file);
                  toast.success(`Uploaded "${clip.name}"`);
                  updateConfig("ambience", `custom:${clip.id}`);
                } catch (err) {
                  toast.error(err instanceof ApiError ? err.message : "Upload failed");
                }
              }}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadAmbienceClip.isPending}
            >
              {uploadAmbienceClip.isPending ? "Uploading…" : "Upload audio (max 5MB, 120s)"}
            </Button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Switch
            id="thinking_sound"
            checked={config.thinking_sound}
            onCheckedChange={(v) => updateConfig("thinking_sound", v)}
          />
          <Label htmlFor="thinking_sound">Play a sound while the agent is thinking</Label>
        </div>
      </div>

      <div className="flex flex-col gap-4 rounded-lg border p-4">
        <h3 className="font-medium">Tools</h3>

        <div className="flex flex-wrap items-center gap-8">
          <div className="flex items-center gap-2">
            <Switch
              id="end_call"
              checked={endCallTool?.enabled ?? false}
              onCheckedChange={(v) => toggleBuiltin("end_call", v)}
            />
            <Label htmlFor="end_call">Can end the call</Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="transfer_call"
              checked={transferTool?.enabled ?? false}
              onCheckedChange={(v) =>
                toggleBuiltin("transfer_call", v, transferTool?.config ?? { transfer_to: "" })
              }
            />
            <Label htmlFor="transfer_call">Can transfer to a human</Label>
          </div>
          {transferTool?.enabled && (
            <Input
              placeholder="+15551234567"
              className="w-48"
              value={(transferTool.config?.transfer_to as string) ?? ""}
              onChange={(e) => toggleBuiltin("transfer_call", true, { transfer_to: e.target.value })}
            />
          )}
          <div className="flex items-center gap-2">
            <Switch
              id="send_dtmf"
              checked={dtmfTool?.enabled ?? false}
              onCheckedChange={(v) => toggleBuiltin("send_dtmf", v)}
            />
            <Label htmlFor="send_dtmf">Can press touch-tone (DTMF) keys</Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="lookup_knowledge"
              checked={knowledgeTool?.enabled ?? false}
              onCheckedChange={(v) => toggleBuiltin("lookup_knowledge", v)}
            />
            <Label htmlFor="lookup_knowledge">Can search the knowledge base</Label>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <Label className="text-xs text-muted-foreground">
            Webhook tools — reusable across agents, edited on their own page
          </Label>
          {legacyWebhookTools.map((tool, i) => (
            <div
              key={i}
              className="flex flex-col gap-1 rounded-md border border-dashed p-3 text-sm text-muted-foreground"
            >
              <span className="font-medium text-foreground">{tool.name || "(unnamed)"}</span>
              <span>
                Legacy inline webhook tool — recreate it under Tools to edit or attach it to
                other agents.
              </span>
            </div>
          ))}
          {orgTools?.length === 0 && legacyWebhookTools.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No webhook tools yet — create one to let this agent fetch data or trigger actions
              mid-call.
            </p>
          )}
          {orgTools?.map((tool) => {
            const ref = tools.find(
              (t): t is ToolRef => t.type === "tool_ref" && t.tool_id === tool.id,
            );
            return (
              <div
                key={tool.id}
                className="flex items-center justify-between gap-3 rounded-md border p-3"
              >
                <div className="flex items-center gap-3">
                  <Switch
                    id={`tool-${tool.id}`}
                    checked={ref?.enabled ?? false}
                    onCheckedChange={(v) => toggleToolRef(tool.id, v)}
                  />
                  <Label htmlFor={`tool-${tool.id}`} className="flex flex-col items-start gap-0.5">
                    <span className="font-medium">{tool.name}</span>
                    <span className="text-xs font-normal text-muted-foreground">
                      {tool.description}
                    </span>
                  </Label>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  nativeButton={false}
                  render={<Link href={`/tools/${tool.id}`} />}
                >
                  Edit
                </Button>
              </div>
            );
          })}
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            nativeButton={false}
            render={<Link href="/tools/new" />}
          >
            + New tool
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border p-4">
        <h3 className="font-medium">Post-call analysis</h3>
        <p className="text-sm text-muted-foreground">
          Every call gets a summary, outcome, and sentiment automatically. Add extra fields to
          extract here as JSON — {"{"}&quot;field_name&quot;: &quot;description of what to
          extract&quot;{"}"}.
        </p>
        <Textarea
          rows={4}
          className="font-mono text-xs"
          value={analysisSchemaText}
          onChange={(e) => {
            const text = e.target.value;
            setAnalysisSchemaText(text);
            try {
              const parsed = JSON.parse(text);
              setAnalysisSchemaError(null);
              updateConfig("analysis_schema", parsed);
            } catch {
              setAnalysisSchemaError("Invalid JSON — not saved until this is fixed");
            }
          }}
        />
        {analysisSchemaError && <p className="text-xs text-destructive">{analysisSchemaError}</p>}
      </div>

      <div className="flex justify-end gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : mode === "create" ? "Create agent" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
