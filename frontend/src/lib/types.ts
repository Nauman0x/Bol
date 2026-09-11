export type Language = "en" | "ur" | "auto";

export interface AgentConfig {
  system_prompt: string;
  greeting: string;
  language: Language;
  voice_id: string;
  llm_model: string;
  temperature: number;
  max_call_duration_sec: number;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  config: AgentConfig;
  created_at: string;
}

export interface Voice {
  id: string;
  label: string;
  language: string;
}

export interface Call {
  id: string;
  org_id: string;
  agent_id: string;
  direction: string;
  status: "in_progress" | "completed" | "failed";
  livekit_room_name: string;
  started_at: string;
  ended_at: string | null;
  duration_sec: number | null;
  end_reason: string | null;
}

export interface CallEvent {
  id: string;
  call_id: string;
  ts: string;
  type: "transcript_user" | "transcript_agent" | "status" | "error";
  payload: Record<string, unknown>;
}

export interface User {
  id: string;
  org_id: string;
  email: string;
  name: string;
  role: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface TestSessionResponse {
  call_id: string;
  room_name: string;
  livekit_url: string;
  token: string;
}
