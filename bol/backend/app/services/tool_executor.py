"""Shared HTTP execution for Tool calls (app/models/tool.py) — imported by
both the dashboard's POST /tools/{id}/test (app/routers/tools.py) and the
worker's function-tool wrapper (worker/tools.py), so what a "Run test" click
does and what actually happens on a live call can never drift apart (same
rationale as app/tts_providers.py).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.tool import DYNAMIC_VARS, ToolParam
from app.services.ssrf_guard import check_webhook_url

logger = logging.getLogger("BOL.tools")

_RESPONSE_TRUNCATE_BYTES = 2000
_RETRY_BACKOFF_SEC = 0.5


def build_llm_schema(name: str, description: str, params: list[ToolParam]) -> dict:
    """JSON Schema exposed to the LLM as this tool's function-call
    signature — contains ONLY source=="llm" params, so the model can never
    fill in a value (call_id, an auth token, ...) it has no business
    inventing. Path/query/body/header split happens later in resolve_params,
    not here — the LLM only sees names/types/descriptions."""
    properties: dict[str, dict] = {}
    required: list[str] = []
    for param in params:
        if param.source != "llm":
            continue
        prop: dict[str, Any] = {"type": _JSON_SCHEMA_TYPE.get(param.type, "string")}
        if param.description:
            prop["description"] = param.description
        properties[param.name] = prop
        if param.required:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "parameters": schema}


_JSON_SCHEMA_TYPE = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "object": "object",
    "array": "array",
}


def build_dynamic_context(
    *,
    call_id: str = "",
    agent_id: str = "",
    org_id: str = "",
    caller_number: str = "",
    to_number: str = "",
    direction: str = "",
    transport: str = "",
) -> dict[str, str]:
    """Values a Tool's `dynamic`-source params may pull from — see
    DYNAMIC_VARS. Built once per call in worker/agent.py from context already
    in scope there; a test run (app/routers/tools.py) passes placeholders."""
    ctx = {
        "call_id": call_id,
        "agent_id": agent_id,
        "org_id": org_id,
        "caller_number": caller_number,
        "to_number": to_number,
        "direction": direction,
        "transport": transport,
        "now_iso": datetime.now(UTC).isoformat(),
    }
    assert set(ctx) == set(DYNAMIC_VARS)
    return ctx


class ToolParamError(ValueError):
    """A param's value couldn't be resolved (missing required LLM arg,
    unknown dynamic var, or a URL path placeholder that was never filled)."""


def resolve_params(
    url_template: str, params: list[ToolParam], llm_args: dict, dynamic_ctx: dict
) -> tuple[str, dict[str, str], dict[str, Any], dict[str, str]]:
    """Merges LLM-supplied, constant, and dynamic values and splits them by
    `location`. Returns (url, query, body, extra_headers). Raises
    ToolParamError on a missing required value or an unresolved path
    placeholder — never silently drops a param."""
    path_values: dict[str, str] = {}
    query: dict[str, str] = {}
    body: dict[str, Any] = {}
    headers: dict[str, str] = {}

    for param in params:
        if param.source == "llm":
            if param.name in llm_args:
                value = llm_args[param.name]
            elif param.required:
                raise ToolParamError(f"missing required argument: {param.name}")
            else:
                continue
        elif param.source == "constant":
            value = param.value
        else:  # dynamic
            if param.value not in dynamic_ctx:
                raise ToolParamError(f"unknown dynamic variable: {param.value}")
            value = dynamic_ctx[param.value]

        if param.location == "path":
            path_values[param.name] = str(value)
        elif param.location == "query":
            query[param.name] = str(value)
        elif param.location == "header":
            headers[param.name] = str(value)
        else:  # body
            body[param.name] = value

    # quote() with safe="" so a value can't inject a new path segment (or,
    # via a leading "//host", a new host) via "../" or an embedded slash.
    url = url_template
    for name, value in path_values.items():
        url = url.replace("{" + name + "}", quote(value, safe=""))
    if "{" in url and "}" in url:
        raise ToolParamError(f"unresolved path placeholder in url: {url_template}")

    return url, query, body, headers


@dataclass
class ToolExecutionResult:
    ok: bool
    status_code: int | None
    duration_ms: int
    request_url: str
    request_header_names: list[str] = field(default_factory=list)
    response_body: str | None = None
    extracted: dict[str, Any] | None = None
    error: str | None = None


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


async def run_tool(
    *,
    url: str,
    method: str,
    query: dict[str, str],
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_sec: float,
    retry_on_failure: bool,
    response_extract: list,
    client: httpx.AsyncClient,
) -> ToolExecutionResult:
    """Issues the resolved HTTP request. SSRF-checks the fully resolved URL
    (after path templating) rather than the stored template, since a path
    param is exactly the kind of value that could otherwise be used to
    rewrite the request onto an internal host."""
    try:
        await check_webhook_url(url)
    except ValueError as exc:
        return ToolExecutionResult(
            ok=False, status_code=None, duration_ms=0, request_url=url, error=str(exc)
        )

    started = time.monotonic()
    attempts = 2 if retry_on_failure else 1
    last_exc: Exception | None = None
    resp: httpx.Response | None = None

    for attempt in range(attempts):
        try:
            resp = await client.request(
                method,
                url,
                params=query or None,
                # location="body" is an explicit per-param choice (see
                # resolve_params) — respected regardless of HTTP method
                # rather than silently dropped for GET.
                json=body or None,
                headers=headers or None,
                timeout=timeout_sec,
            )
            if resp.status_code >= 500 and attempt < attempts - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SEC)
                continue
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < attempts - 1 and _is_retryable(exc):
                await asyncio.sleep(_RETRY_BACKOFF_SEC)
                continue
            break

    duration_ms = round((time.monotonic() - started) * 1000)

    if resp is None:
        logger.warning("tool call to %s failed: %s", url, last_exc)
        return ToolExecutionResult(
            ok=False,
            status_code=None,
            duration_ms=duration_ms,
            request_url=url,
            request_header_names=list(headers.keys()),
            error=_speakable_error(last_exc),
        )

    text = resp.text[:_RESPONSE_TRUNCATE_BYTES]
    extracted = None
    if response_extract:
        try:
            data = resp.json()
        except ValueError:
            data = None
        if data is not None:
            from app.services.tool_response import extract_path

            extracted = {rule.name: extract_path(data, rule.path) for rule in response_extract}

    ok = resp.status_code < 400
    return ToolExecutionResult(
        ok=ok,
        status_code=resp.status_code,
        duration_ms=duration_ms,
        request_url=url,
        request_header_names=list(headers.keys()),
        response_body=text,
        extracted=extracted,
        error=None if ok else f"request failed with status {resp.status_code}",
    )


def _speakable_error(exc: Exception | None) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "the service timed out"
    if isinstance(exc, httpx.ConnectError):
        return "the service is currently unavailable"
    return "the service is currently unavailable"
