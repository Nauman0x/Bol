"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, apiUpload } from "@/lib/api";
import type {
  Agent,
  AgentConfig,
  AgentTool,
  AmbienceClip,
  AnalyticsSummary,
  ApiKey,
  ApiKeyCreated,
  Call,
  CallDetail,
  CallDirection,
  CallStatus,
  InterruptionPresetsResponse,
  KnowledgeDocument,
  LatencyAnalytics,
  ListenSession,
  Organization,
  PhoneNumber,
  PhoneNumberProvider,
  RecordingUrl,
  TeamMember,
  TeamMemberInvited,
  TestSession,
  Tool,
  ToolInput,
  ToolTestResult,
  TtsProviderId,
  TtsProviderInfo,
  Voice,
  Webhook,
  WebhookCreated,
  WebhookEvent,
} from "@/lib/types";

// --- Agents ---

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiRequest<Agent[]>("/agents"),
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: ["agents", id],
    queryFn: () => apiRequest<Agent>(`/agents/${id}`),
    enabled: !!id,
  });
}

interface AgentInput {
  name: string;
  config: AgentConfig;
  tools: AgentTool[];
  is_active?: boolean;
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AgentInput) =>
      apiRequest<Agent>("/agents", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useUpdateAgent(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: Partial<AgentInput>) =>
      apiRequest<Agent>(`/agents/${id}`, { method: "PATCH", body: input }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["agents", id] });
    },
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/agents/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export interface HealthConfig {
  livekit: boolean;
  groq: boolean;
  fish: boolean;
  chatterbox: boolean;
  sip_trunk: boolean;
}

export function useHealthConfig() {
  return useQuery({
    queryKey: ["health_config"],
    queryFn: () => apiRequest<HealthConfig>("/health/config", { auth: false }),
  });
}

export function useCreateTestSession() {
  return useMutation({
    mutationFn: (agentId: string) =>
      apiRequest<TestSession>(`/agents/${agentId}/test-session`, { method: "POST" }),
  });
}

// --- Phone numbers ---

export function usePhoneNumbers() {
  return useQuery({
    queryKey: ["phone_numbers"],
    queryFn: () => apiRequest<PhoneNumber[]>("/phone_numbers"),
  });
}

export function useCreatePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      e164: string;
      provider?: PhoneNumberProvider;
      livekit_trunk_id?: string | null;
      inbound_agent_id?: string | null;
    }) => apiRequest<PhoneNumber>("/phone_numbers", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phone_numbers"] }),
  });
}

export function useUpdatePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: string; inbound_agent_id?: string | null }) =>
      apiRequest<PhoneNumber>(`/phone_numbers/${id}`, { method: "PATCH", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phone_numbers"] }),
  });
}

export function useDeletePhoneNumber() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/phone_numbers/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phone_numbers"] }),
  });
}

// --- TTS providers + voices ---

export function useTtsProviders() {
  return useQuery({
    queryKey: ["tts_providers"],
    queryFn: () => apiRequest<TtsProviderInfo[]>("/tts-providers"),
  });
}

export function useVoices(provider?: TtsProviderId) {
  return useQuery({
    queryKey: ["voices", provider ?? "all"],
    queryFn: () => apiRequest<Voice[]>("/voices", { query: { provider } }),
  });
}

// --- Interruption presets ---

export function useInterruptionPresets() {
  return useQuery({
    queryKey: ["interruption_presets"],
    queryFn: () => apiRequest<InterruptionPresetsResponse>("/interruption-presets"),
  });
}

// --- Ambience clips ---

export function useAmbienceClips() {
  return useQuery({
    queryKey: ["ambience_clips"],
    queryFn: () => apiRequest<AmbienceClip[]>("/ambience"),
  });
}

export function useUploadAmbienceClip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return apiUpload<AmbienceClip>("/ambience", formData);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ambience_clips"] }),
  });
}

export function useDeleteAmbienceClip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/ambience/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ambience_clips"] }),
  });
}

// --- Calls ---

interface CallFilters {
  agent_id?: string;
  direction?: CallDirection;
  status?: CallStatus;
}

export function useCalls(filters: CallFilters = {}) {
  return useQuery({
    queryKey: ["calls", filters],
    queryFn: () => apiRequest<Call[]>("/calls", { query: { ...filters } }),
    refetchInterval: 5000,
  });
}

export function useCall(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", "detail", id],
    queryFn: () => apiRequest<CallDetail>(`/calls/${id}`),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const terminal: CallStatus[] = ["completed", "failed", "no_answer", "busy"];
      return status && terminal.includes(status) ? false : 3000;
    },
  });
}

export function useCreateOutboundCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { agent_id: string; to_number: string; phone_number_id?: string }) =>
      apiRequest<Call>("/calls/outbound", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["calls"] }),
  });
}

export function useHangupCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<Call>(`/calls/${id}/hangup`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["calls"] }),
  });
}

export function useListenToCall() {
  return useMutation({
    mutationFn: (id: string) => apiRequest<ListenSession>(`/calls/${id}/listen`),
  });
}

export function useCallRecording(id: string | undefined, hasRecording: boolean) {
  return useQuery({
    queryKey: ["calls", "recording", id],
    queryFn: () => apiRequest<RecordingUrl>(`/calls/${id}/recording`),
    enabled: !!id && hasRecording,
    // Presigned URLs are short-lived (5 min server-side) — refetch well
    // before that so a long-open tab doesn't end up with a dead <audio src>.
    staleTime: 4 * 60 * 1000,
  });
}

// --- Webhooks ---

export function useWebhooks() {
  return useQuery({
    queryKey: ["webhooks"],
    queryFn: () => apiRequest<Webhook[]>("/webhooks"),
  });
}

export function useCreateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { url: string; events?: WebhookEvent[] }) =>
      apiRequest<WebhookCreated>("/webhooks", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

export function useDeleteWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/webhooks/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

// --- Tools ---

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: () => apiRequest<Tool[]>("/tools"),
  });
}

export function useTool(id: string) {
  return useQuery({
    queryKey: ["tools", id],
    queryFn: () => apiRequest<Tool>(`/tools/${id}`),
    enabled: !!id,
  });
}

export function useCreateTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ToolInput) => apiRequest<Tool>("/tools", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useUpdateTool(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: Partial<ToolInput>) =>
      apiRequest<Tool>(`/tools/${id}`, { method: "PATCH", body: input }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tools"] });
      qc.invalidateQueries({ queryKey: ["tools", id] });
    },
  });
}

export function useDeleteTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/tools/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useTestTool(id: string) {
  return useMutation({
    mutationFn: (llm_args: Record<string, unknown>) =>
      apiRequest<ToolTestResult>(`/tools/${id}/test`, { method: "POST", body: { llm_args } }),
  });
}

// --- Analytics ---

export function useAnalytics() {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: () => apiRequest<AnalyticsSummary>("/analytics/summary"),
  });
}

export function useLatencyAnalytics() {
  return useQuery({
    queryKey: ["analytics", "latency"],
    queryFn: () => apiRequest<LatencyAnalytics>("/analytics/latency"),
  });
}

// --- Organization / team / API keys ---

export function useOrganization() {
  return useQuery({
    queryKey: ["organization"],
    queryFn: () => apiRequest<Organization>("/organization"),
  });
}

export function useUpdateOrganization() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string }) =>
      apiRequest<Organization>("/organization", { method: "PATCH", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["organization"] }),
  });
}

export function useTeam() {
  return useQuery({
    queryKey: ["team"],
    queryFn: () => apiRequest<TeamMember[]>("/team"),
  });
}

export function useInviteTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; name: string; role: string }) =>
      apiRequest<TeamMemberInvited>("/team/invite", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["team"] }),
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: ["api_keys"],
    queryFn: () => apiRequest<ApiKey[]>("/api_keys"),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string }) =>
      apiRequest<ApiKeyCreated>("/api_keys", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api_keys"] }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/api_keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api_keys"] }),
  });
}

// --- Knowledge base ---

export function useKnowledgeDocuments() {
  return useQuery({
    queryKey: ["knowledge"],
    queryFn: () => apiRequest<KnowledgeDocument[]>("/knowledge"),
  });
}

export function useCreateKnowledgeDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; content: string }) =>
      apiRequest<KnowledgeDocument>("/knowledge", { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}

export function useDeleteKnowledgeDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/knowledge/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}
