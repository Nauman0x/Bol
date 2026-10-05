export type UserRole = "owner" | "admin" | "member";

export interface User {
  id: string;
  org_id: string;
  email: string;
  name: string;
  role: UserRole;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// "auto" or a lowercase 2-3 letter ISO-639 code — see LANGUAGE_OPTIONS in
// agent-form.tsx for the list offered in the UI. Not a closed union: the
// backend accepts any such code (app/schemas/agent.py), not just the ones
// listed there.
export type AgentLanguage = string;

export interface WebhookTool {
  type: "webhook";
  name: string;
  description: string;
  url: string;
  method: "GET" | "POST";
  params_schema: Record<string, unknown>;
}

export interface BuiltinTool {
  type: "end_call" | "transfer_call" | "send_dtmf" | "lookup_knowledge";
  enabled: boolean;
  config: Record<string, unknown>;
}

// References a reusable Tool (see below) by id — the current, first-class
// way an agent picks up a webhook tool. Replaces WebhookTool for all new
// agents; WebhookTool only still appears on an agent saved before the
// tools migration ran and never resaved since.
export interface ToolRef {
  type: "tool_ref";
  tool_id: string;
  enabled: boolean;
}

export type AgentTool = WebhookTool | BuiltinTool | ToolRef;

export type TtsProviderId = "groq" | "fish" | "chatterbox";

export interface AgentConfig {
  system_prompt: string;
  greeting: string;
  language: AgentLanguage;
  voice_id: string;
  // null = use the platform-wide default (TTS_PROVIDER env var).
  tts_provider: TtsProviderId | null;
  llm_model: string;
  temperature: number;
  max_call_duration_sec: number;
  interruption_enabled: boolean;
  // Human-facing barge-in preset — see the InterruptionPreset table fetched
  // from GET /interruption-presets for what each expands to. "custom" reads
  // the four explicit fields below.
  interruption_style: "instant" | "balanced" | "patient" | "custom";
  // "vad" (default) works with any STT. "adaptive" is an ML backchannel
  // classifier — costs more and needs a streaming STT; disabled in the UI
  // when the platform can't support it (see useInterruptionPresets).
  interruption_mode: "vad" | "adaptive";
  // Only read when interruption_style === "custom".
  interruption_min_duration: number;
  interruption_min_words: number;
  false_interruption_timeout: number;
  // Speak a short "Go ahead." when the caller genuinely interrupts, instead
  // of going silent until the next reply is ready.
  ack_on_interrupt: boolean;
  // "instant" (default) resumes a falsely-interrupted sentence exactly
  // where it was cut off. "connector" re-generates the rest behind a short
  // spoken connector instead — costs an extra LLM+TTS round trip.
  resume_style: "instant" | "connector";
  // A builtin key ("office" | "city" | "forest" | "crowded_room" |
  // "hold_music") or "custom:<AmbienceClip id>". null disables it.
  ambience: string | null;
  ambience_volume: number;
  thinking_sound: boolean;
  // "agent_first" (default) speaks the greeting immediately; "wait_for_caller"
  // stays silent until the callee speaks first (outbound etiquette).
  greeting_mode: "agent_first" | "wait_for_caller";
  // Spoken filler ("One moment...") played while a tool call is running.
  filler_phrases: boolean;
  // Pronunciation/recognition hints passed to the STT provider (brand
  // names, product SKUs, etc.) — see worker/pipeline.py:build_stt.
  boosted_keywords: string[];
  // Extra fields for post-call analysis to extract beyond the default
  // summary/outcome/sentiment, {field_name: description}.
  analysis_schema: Record<string, string>;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  config: AgentConfig;
  tools: AgentTool[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type PhoneNumberProvider = "telnyx" | "twilio";

export interface PhoneNumber {
  id: string;
  org_id: string;
  e164: string;
  provider: string;
  livekit_trunk_id: string | null;
  inbound_agent_id: string | null;
  created_at: string;
}

export interface Voice {
  id: string;
  label: string;
  // Kept for simple callers — always languages[0]. Match against
  // `languages` for filtering (some voices speak several).
  language: string;
  languages: string[];
  provider: string;
}

export interface TtsProviderInfo {
  id: TtsProviderId;
  label: string;
  streaming: boolean;
  configured: boolean;
}

// Mirrors app/interruption.py:InterruptionPreset / GET /interruption-presets.
export interface InterruptionPreset {
  id: "instant" | "balanced" | "patient";
  label: string;
  description: string;
  min_duration: number;
  min_words: number;
  false_interruption_timeout: number;
}

export interface InterruptionPresetsResponse {
  presets: InterruptionPreset[];
  adaptive_supported: boolean;
  adaptive_unsupported_reason: string | null;
}

export interface AmbienceClip {
  id: string;
  org_id: string;
  name: string;
  content_type: string;
  duration_sec: number;
  created_at: string;
}

export type CallDirection = "inbound" | "outbound" | "test";

export type CallStatus =
  | "queued"
  | "ringing"
  | "in_progress"
  | "completed"
  | "failed"
  | "no_answer"
  | "busy";

export type CallTransport = "telephony" | "webrtc";

export interface Call {
  id: string;
  org_id: string;
  agent_id: string;
  phone_number_id: string | null;
  direction: CallDirection;
  to_number: string;
  from_number: string;
  status: CallStatus;
  livekit_room_name: string | null;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  duration_sec: number | null;
  end_reason: string | null;
  // Playback URLs are never stored — fetch one on demand via GET
  // /calls/{id}/recording (see useCallRecording), which presigns a
  // short-lived S3 URL each time.
  has_recording: boolean;
  transport: CallTransport | null;
  tts_provider: string | null;
  llm_model: string | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  cost_estimate: number | null;
  created_at: string;
}

export type CallEventType =
  | "transcript_user"
  | "transcript_agent"
  | "tool_call"
  | "tool_result"
  | "status"
  | "error";

// Present on transcript_user/transcript_agent event payloads when the
// worker's LatencyCollector captured metrics for that turn — see
// worker/latency.py. Keys mirror livekit.agents.llm.chat_context.MetricsReport;
// which subset is present depends on role (user vs assistant) and provider.
export interface TurnTimings {
  transcription_delay?: number;
  end_of_turn_delay?: number;
  on_user_turn_completed_delay?: number;
  e2e_latency?: number;
  llm_node_ttft?: number;
  llm_node_ttfs?: number;
  tts_node_ttfb?: number;
  playback_latency?: number;
  llm_node_tps?: number;
}

export interface CallEvent {
  id: string;
  call_id: string;
  ts: string;
  type: CallEventType;
  payload: Record<string, unknown> & { timings?: TurnTimings };
}

// Mirrors worker/latency.py:LatencyCollector.summary().
export interface LatencyStageStats {
  count: number;
  avg: number;
  min: number;
  max: number;
  p50: number;
  p95: number;
}

// Present only when at least one interruption-related event was recorded
// this call — absent on old calls and on calls with no barge-in activity.
export interface InterruptionStats {
  true: number;
  false: number;
  resumed: number;
  acked: number;
  connector: number;
  style: string | null;
  mode_effective: string | null;
}

export interface LatencyStats {
  turn_count: number;
  stages: Record<string, LatencyStageStats>;
  providers: Record<string, string>;
  interruptions?: InterruptionStats;
}

// Shape produced by app/services/call_analysis.py — "extracted" is only
// present when the agent's analysis_schema requested custom fields.
export interface CallAnalysis {
  summary?: string;
  outcome?: string;
  sentiment?: string;
  extracted?: Record<string, unknown>;
}

export interface CallDetail extends Call {
  events: CallEvent[];
  latency_stats: LatencyStats | null;
  analysis: CallAnalysis | null;
}

export interface TestSession {
  livekit_url: string;
  room_name: string;
  token: string;
  call_id: string;
}

export interface ListenSession {
  livekit_url: string;
  room_name: string;
  token: string;
}

export interface RecordingUrl {
  url: string;
}

export interface CallsByDay {
  date: string;
  count: number;
}

export interface AnalyticsSummary {
  total_calls: number;
  total_minutes: number;
  answer_rate: number;
  avg_duration_sec: number;
  calls_by_day: CallsByDay[];
}

export interface LatencyGroupStat {
  key: string;
  call_count: number;
  avg_latency_ms: number;
  avg_p95_latency_ms: number;
}

export interface LatencyOverall {
  call_count: number;
  avg_latency_ms: number | null;
  avg_p95_latency_ms: number | null;
  min_latency_ms: number | null;
  max_latency_ms: number | null;
}

export interface LatencyAnalytics {
  overall: LatencyOverall;
  by_transport: LatencyGroupStat[];
  by_tts_provider: LatencyGroupStat[];
  by_llm_model: LatencyGroupStat[];
}

export interface Organization {
  id: string;
  name: string;
  created_at: string;
}

export interface TeamMember {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  created_at: string;
}

export interface TeamMemberInvited {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  temp_password: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  key: string;
}

export type WebhookEvent = "call.completed";

export interface Webhook {
  id: string;
  url: string;
  events: WebhookEvent[];
  is_active: boolean;
  created_at: string;
}

export interface WebhookCreated extends Webhook {
  // Returned once, at creation, and never again — the caller must store it.
  secret: string;
}

export interface KnowledgeDocument {
  id: string;
  name: string;
  chunk_count: number;
  created_at: string;
}

// Mirrors app/schemas/tool.py:DYNAMIC_VARS — values a tool's "dynamic"
// params can pull from at call time, resolved by the worker itself, never
// invented by the LLM.
export const DYNAMIC_VARS = [
  "call_id",
  "agent_id",
  "org_id",
  "caller_number",
  "to_number",
  "direction",
  "transport",
  "now_iso",
] as const;
export type DynamicVar = (typeof DYNAMIC_VARS)[number];

export type ToolParamLocation = "path" | "query" | "body" | "header";
export type ToolParamType = "string" | "number" | "integer" | "boolean" | "object" | "array";
export type ToolParamSource = "llm" | "constant" | "dynamic";

// Mirrors app/schemas/tool.py:ToolParam. `value` is only meaningful for
// source "constant" (a literal) or "dynamic" (a DynamicVar key) — ignored
// for "llm", where the model supplies the value at call time.
export interface ToolParam {
  name: string;
  location: ToolParamLocation;
  type: ToolParamType;
  description: string;
  required: boolean;
  source: ToolParamSource;
  value: string;
}

// Mirrors app/schemas/tool.py:ToolHeader. A "secret" header's `value` is
// never round-tripped through this API — see Tool.secret_refs_set below —
// only `secret_ref`, the key a matching entry in a create/update's
// `secrets` array supplies the plaintext for.
export interface ToolHeader {
  name: string;
  value_type: "literal" | "secret";
  value: string;
  secret_ref: string | null;
}

export interface PreToolSpeech {
  mode: "none" | "fixed" | "auto";
  phrase: string;
}

// Mirrors app/schemas/tool.py:ResponseExtract — a dotted path into the
// tool's JSON response (e.g. "data.booking.id" or "results[*].name") pulled
// out into a small object for the LLM instead of the full raw response.
export interface ResponseExtract {
  name: string;
  path: string;
  description: string;
}

export interface ToolSecretInput {
  secret_ref: string;
  value: string;
}

// A reusable, org-scoped webhook tool an agent can attach via ToolRef.
// Mirrors app/schemas/tool.py:ToolResponse.
export interface Tool {
  id: string;
  org_id: string;
  name: string;
  description: string;
  is_active: boolean;
  url: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  params: ToolParam[];
  headers: ToolHeader[];
  timeout_sec: number;
  retry_on_failure: boolean;
  blocking: boolean;
  pre_tool_speech: PreToolSpeech;
  response_extract: ResponseExtract[];
  // Names of headers whose value_type is "secret" and that currently have a
  // stored value — the form renders these as "••••••", never a plaintext.
  secret_refs_set: string[];
  created_at: string;
  updated_at: string;
}

// Body for POST/PATCH /tools — see app/schemas/tool.py:ToolCreate/ToolUpdate.
export interface ToolInput {
  name: string;
  description: string;
  is_active: boolean;
  url: string;
  method: Tool["method"];
  params: ToolParam[];
  headers: ToolHeader[];
  secrets: ToolSecretInput[];
  timeout_sec: number;
  retry_on_failure: boolean;
  blocking: boolean;
  pre_tool_speech: PreToolSpeech;
  response_extract: ResponseExtract[];
}

export interface ToolTestResult {
  ok: boolean;
  status_code: number | null;
  duration_ms: number;
  request_headers: string[];
  request_url: string;
  response_body: string | null;
  extracted: Record<string, unknown> | null;
  error: string | null;
}
