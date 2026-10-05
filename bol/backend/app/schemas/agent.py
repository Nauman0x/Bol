import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# "auto" (detect at runtime) or a 2-3 letter ISO-639 code, e.g. "en", "es",
# "hi", "yue". Not validated against a fixed enum — new languages shouldn't
# require a code change here; the actual constraint is "does the chosen STT/
# TTS/LLM combination support it", which is a runtime concern per-provider,
# not something this schema can know.
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}$")


class WebhookTool(BaseModel):
    type: Literal["webhook"] = "webhook"
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    url: str
    method: Literal["GET", "POST"] = "POST"
    params_schema: dict = Field(default_factory=dict)


class BuiltinTool(BaseModel):
    type: Literal["end_call", "transfer_call", "send_dtmf", "lookup_knowledge"]
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class ToolRef(BaseModel):
    """References a reusable Tool (app/models/tool.py) by id — the tool's
    own config lives in the tools table, not here. Replaces WebhookTool for
    all new agents; WebhookTool is kept only for pre-migration agents that
    haven't been resaved yet (see the tools migration's data backfill)."""

    type: Literal["tool_ref"] = "tool_ref"
    tool_id: uuid.UUID
    enabled: bool = True


class AgentConfig(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=8000)
    greeting: str = Field(default="", max_length=1000)
    # "auto" or a lowercase 2-3 letter ISO-639 code — see _LANGUAGE_PATTERN.
    language: str = "en"
    voice_id: str = "default"
    # None means "use the platform-wide TTS_PROVIDER default" (see
    # app/config.py) rather than hardcoding a provider per agent.
    tts_provider: Literal["groq", "fish", "chatterbox"] | None = None
    llm_model: str = "qwen/qwen3.6-27b"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_call_duration_sec: int = Field(default=600, ge=30, le=7200)
    interruption_enabled: bool = True
    # Human-facing barge-in preset — see app/interruption.py for the concrete
    # numbers each expands to. "custom" reads the four explicit fields below;
    # any other value ignores them. "balanced" reproduces the values every
    # agent ran with before this feature existed, so agents saved before
    # these fields existed keep behaving identically.
    interruption_style: Literal["instant", "balanced", "patient", "custom"] = "balanced"
    # "vad": simple voice-activity detection (default, works with any STT).
    # "adaptive": ML backchannel classifier that tells "mhm"/"yeah" apart from
    # a real interruption — costs extra LiveKit inference and needs a
    # streaming, word-aligned STT (STT_PROVIDER=livekit). Applies across all
    # styles, not just "custom" — it's a detection-accuracy axis, patience is
    # a timing axis. Silently downgraded to "vad" by the worker (with a
    # logged + reported warning) when the deployment's STT can't support it —
    # see app/interruption.py:adaptive_supported and worker/pipeline.py.
    interruption_mode: Literal["vad", "adaptive"] = "vad"
    # Only read when interruption_style == "custom" — see
    # app/interruption.py:resolve_interruption.
    interruption_min_duration: float = Field(default=0.3, ge=0.05, le=3.0)
    interruption_min_words: int = Field(default=0, ge=0, le=10)
    false_interruption_timeout: float = Field(default=2.0, ge=0.3, le=10.0)
    # Speak a short acknowledgment ("Go ahead.") when the caller genuinely
    # interrupts, instead of going silent until the next reply is ready. Off
    # by default: it fills what would otherwise be silence but still adds to
    # perceived time-to-answer. See worker/interruption.py.
    ack_on_interrupt: bool = False
    # "instant" (default): resume a falsely-interrupted sentence exactly
    # where it was cut off, per the framework's own behavior. "connector":
    # re-generate the rest of the reply behind a short spoken connector
    # ("Sorry, as I was saying...") instead — costs a full extra LLM+TTS
    # round trip and can restate the point; see worker/interruption.py for
    # why this is opt-in rather than the default.
    resume_style: Literal["instant", "connector"] = "instant"
    # "agent_first" (default): speak the greeting immediately. "wait_for_caller":
    # stay silent until the callee says something first (common outbound
    # etiquette — many people answer with "Hello?"), then speak the greeting.
    greeting_mode: Literal["agent_first", "wait_for_caller"] = "agent_first"
    # Spoken filler ("One moment...") played when a tool call starts — hides
    # webhook-tool latency (up to 10s, see worker/tools.py) instead of dead
    # air. Off by default since not every agent has slow tools.
    filler_phrases: bool = False
    # Terms passed to the STT provider as a pronunciation/recognition hint
    # (e.g. brand names, product SKUs) — see worker/pipeline.py:build_stt.
    # Only affects the livekit/Deepgram-Flux and AssemblyAI STT paths; a
    # provider that doesn't support keyword boosting silently ignores this.
    boosted_keywords: list[str] = Field(default_factory=list)
    # Background ambience: a builtin key (office/city/crowded_room/forest/
    # hold_music) or "custom:<ambience_clip id>". None disables it.
    # 1.0 = the built-in clip's loudness-normalized baseline (see
    # worker/pipeline.py:_BUILTIN_AMBIENCE_GAIN) — not unity gain on the raw
    # file, which for some bundled clips is nearly silent. Allowed up to 1.5
    # for a louder-than-baseline option; values above ~1.0 may clip on the
    # louder clips (crowded_room, hold_music), which is an acceptable
    # tradeoff for an explicit "louder" choice.
    ambience: str | None = None
    ambience_volume: float = Field(default=0.2, ge=0.0, le=1.5)
    thinking_sound: bool = False
    # Optional per-agent fields for post-call analysis to extract beyond the
    # default summary/outcome/sentiment, e.g. {"appointment_time": "the time
    # the caller agreed to, or null"}. Empty means summary/outcome/sentiment
    # only — see app/services/call_analysis.py.
    analysis_schema: dict[str, str] = Field(default_factory=dict)

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "auto" or _LANGUAGE_PATTERN.match(normalized):
            return normalized
        raise ValueError(
            "language must be \"auto\" or a 2-3 letter ISO-639 code (e.g. \"en\", \"es\", \"hi\")"
        )


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    config: AgentConfig
    tools: list[WebhookTool | BuiltinTool | ToolRef] = Field(default_factory=list)
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: AgentConfig | None = None
    tools: list[WebhookTool | BuiltinTool | ToolRef] | None = None
    is_active: bool | None = None


class TestSessionResponse(BaseModel):
    livekit_url: str
    room_name: str
    token: str
    call_id: uuid.UUID


class AgentResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    config: dict
    tools: list
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
