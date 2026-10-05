"""Tool = a reusable, org-scoped webhook an agent can call mid-call. See
app/services/tool_executor.py for how ToolParam/headers/response_extract are
resolved and called, and worker/tools.py for how a ToolResolved becomes a
LiveKit function tool.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Values the tool executor fills in itself at call time — never invented by
# the LLM. Kept as a plain tuple (not a DB-driven registry) since each entry
# corresponds to a specific field already in scope in worker/agent.py.
DYNAMIC_VARS: tuple[str, ...] = (
    "call_id",
    "agent_id",
    "org_id",
    "caller_number",
    "to_number",
    "direction",
    "transport",
    "now_iso",
)


class ToolParam(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: Literal["path", "query", "body", "header"] = "query"
    type: Literal["string", "number", "integer", "boolean", "object", "array"] = "string"
    description: str = Field(default="", max_length=500)
    required: bool = False
    # "llm": the model fills this in — the ONLY kind exposed in the
    # function-call schema built by tool_executor.build_llm_schema.
    # "constant": a fixed value baked into the tool definition.
    # "dynamic": resolved at call time from DYNAMIC_VARS.
    source: Literal["llm", "constant", "dynamic"] = "llm"
    # Constant literal, or a DYNAMIC_VARS key — meaning depends on `source`;
    # unused when source == "llm".
    value: str = ""


class ToolHeader(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value_type: Literal["literal", "secret"] = "literal"
    # Set when value_type == "literal". Ignored (and should be omitted) for
    # "secret" — secret values live only in Tool.secrets_enc, keyed by
    # secret_ref, and are never round-tripped through the dashboard API.
    value: str = ""
    # Set when value_type == "secret" — the key into the decrypted
    # {secret_ref: plaintext} map. Stable across edits so a header can be
    # renamed without invalidating its stored secret.
    secret_ref: str | None = None


class PreToolSpeech(BaseModel):
    mode: Literal["none", "fixed", "auto"] = "none"
    # Spoken verbatim when mode == "fixed"; ignored otherwise ("auto" reuses
    # the agent's localized filler phrases, see worker/agent.py:_FILLER_PHRASES).
    phrase: str = Field(default="", max_length=200)


class ResponseExtract(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Dotted path into the JSON response, e.g. "data.booking.id" or
    # "results[0].name" or "items[*].sku" — see app/services/tool_response.py.
    path: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=300)


class ToolBase(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: str = Field(min_length=1, max_length=500)
    is_active: bool = True
    url: str = Field(min_length=1, max_length=2000)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    params: list[ToolParam] = Field(default_factory=list)
    headers: list[ToolHeader] = Field(default_factory=list)
    timeout_sec: float = Field(default=10.0, ge=1.0, le=30.0)
    retry_on_failure: bool = True
    blocking: bool = True
    pre_tool_speech: PreToolSpeech = Field(default_factory=PreToolSpeech)
    response_extract: list[ResponseExtract] = Field(default_factory=list)


class ToolSecretInput(BaseModel):
    """A secret header's plaintext value, submitted alongside ToolCreate/
    ToolUpdate keyed by secret_ref. On update, a secret_ref omitted here
    keeps its previously stored value — the write-only ergonomics ApiKey
    and Webhook.secret already use elsewhere in this API."""

    secret_ref: str
    value: str = Field(min_length=1)


class ToolCreate(ToolBase):
    secrets: list[ToolSecretInput] = Field(default_factory=list)


class ToolUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    )
    description: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    params: list[ToolParam] | None = None
    headers: list[ToolHeader] | None = None
    secrets: list[ToolSecretInput] | None = None
    timeout_sec: float | None = Field(default=None, ge=1.0, le=30.0)
    retry_on_failure: bool | None = None
    blocking: bool | None = None
    pre_tool_speech: PreToolSpeech | None = None
    response_extract: list[ResponseExtract] | None = None


class ToolResponse(ToolBase):
    id: uuid.UUID
    org_id: uuid.UUID
    # Names of headers whose value_type == "secret" and that currently have
    # a stored value — the dashboard renders these as "••••••", never the
    # plaintext (see the model_validator in app/routers/tools.py).
    secret_refs_set: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ToolResolved(ToolBase):
    """Internal-only shape returned to the worker over
    GET /internal/agents/{agent_id}/tools — headers carry decrypted secret
    values inline. Never expose this response model on a user-facing route.
    """

    id: uuid.UUID
    resolved_headers: dict[str, str] = Field(default_factory=dict)


class ToolTestRequest(BaseModel):
    # Values for this tool's source=="llm" params, keyed by param name —
    # the same shape the LLM would produce at call time.
    llm_args: dict = Field(default_factory=dict)


class ToolTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    duration_ms: int
    # header names only, values masked — never echo a secret back verbatim
    # even in a test run initiated by the tool's own owner.
    request_headers: list[str] = Field(default_factory=list)
    request_url: str
    response_body: str | None = None
    extracted: dict | None = None
    error: str | None = None
