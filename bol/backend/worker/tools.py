"""Builds LiveKit function-tools from an agent's `tools` config (see
docs/PLAN.md Phase 4). Two kinds of user-defined tool exist:

- `tool_ref` (current): references a reusable Tool row (app/models/tool.py),
  resolved with secrets decrypted via BOLApiClient.get_agent_tools. Built
  by _make_resolved_tool below, using the shared app/services/tool_executor
  so a dashboard "Run test" and a live call behave identically.
- `webhook` (legacy): the original inline {name, url, method, params_schema}
  shape, pre-migration. Kept as a rollback safety net — new agents never
  produce this after the tools migration backfills it into a `tools` row.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from livekit.agents import RunContext, function_tool
from livekit.agents.llm import RawFunctionTool

from app.schemas.tool import ResponseExtract, ToolParam
from app.services import tool_executor
from app.services.ssrf_guard import check_webhook_url

logger = logging.getLogger("BOL.worker")

_WEBHOOK_TIMEOUT_SEC = 10.0
_WEBHOOK_RESPONSE_TRUNCATE_BYTES = 2000

# Strong refs for fire-and-forget tool calls (blocking=False) — asyncio only
# holds a weak reference to a task, so without this a call can be
# garbage-collected mid-request since nothing else references it. Same
# pattern as agent.py's _filler_tasks.
_background_tasks: set[asyncio.Task] = set()


def _make_webhook_tool(tool_def: dict[str, Any], client: httpx.AsyncClient) -> RawFunctionTool:
    """Legacy inline webhook tool — see module docstring."""
    name = tool_def["name"]
    description = tool_def["description"]
    url = tool_def["url"]
    method = tool_def.get("method", "POST")
    params_schema = tool_def.get("params_schema") or {"type": "object", "properties": {}}

    async def _call(raw_arguments: dict[str, Any]) -> str:
        try:
            await check_webhook_url(url)
            if method == "GET":
                resp = await client.get(url, params=raw_arguments, timeout=_WEBHOOK_TIMEOUT_SEC)
            else:
                resp = await client.post(url, json=raw_arguments, timeout=_WEBHOOK_TIMEOUT_SEC)
            return resp.text[:_WEBHOOK_RESPONSE_TRUNCATE_BYTES]
        except ValueError as exc:
            logger.warning("webhook tool %r blocked: %s", name, exc)
            return f"Error calling {name}: this webhook is not configured correctly."
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            logger.warning("webhook tool %r call failed: %s", name, exc)
            return f"Error calling {name}: the service is currently unavailable."

    return function_tool(
        _call,
        raw_schema={"name": name, "description": description, "parameters": params_schema},
    )


def _make_resolved_tool(
    tool: dict[str, Any],
    *,
    client: httpx.AsyncClient,
    dynamic_ctx: dict[str, str],
) -> RawFunctionTool:
    """Builds a function tool from a ToolResolved dict (see
    app/schemas/tool.py) — the current, first-class tool type."""
    name = tool["name"]
    description = tool["description"]
    params = [ToolParam(**p) for p in tool["params"]]
    response_extract = [ResponseExtract(**r) for r in tool["response_extract"]]
    # Header values (literal or decrypted secret) are already fully
    # resolved server-side by GET /internal/agents/{id}/tools — nothing
    # left to do with tool["headers"] itself here.
    resolved_headers: dict[str, str] = tool.get("resolved_headers", {})
    url_template = tool["url"]
    method = tool["method"]
    timeout_sec = tool["timeout_sec"]
    retry_on_failure = tool["retry_on_failure"]
    blocking = tool["blocking"]

    async def _run(raw_arguments: dict[str, Any]) -> str:
        try:
            url, query, body, path_headers = tool_executor.resolve_params(
                url_template, params, raw_arguments, dynamic_ctx
            )
        except tool_executor.ToolParamError as exc:
            logger.warning("tool %r param resolution failed: %s", name, exc)
            return f"{name} failed: missing or invalid arguments. {exc}"

        headers = {**resolved_headers, **path_headers}
        result = await tool_executor.run_tool(
            url=url,
            method=method,
            query=query,
            body=body,
            headers=headers,
            timeout_sec=timeout_sec,
            retry_on_failure=retry_on_failure,
            response_extract=response_extract,
            client=client,
        )
        if result.error and not result.ok:
            return (
                f"{name} failed: {result.error}. Tell the caller you couldn't complete this "
                "right now, and offer to try again or take a message."
            )
        if result.extracted is not None:
            return json.dumps(result.extracted)
        return result.response_body or "Done."

    async def _call(raw_arguments: dict[str, Any]) -> str:
        if not blocking:
            task = asyncio.create_task(_run(raw_arguments))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            return "Request sent."
        return await _run(raw_arguments)

    schema = tool_executor.build_llm_schema(name, description, params)
    return function_tool(_call, raw_schema=schema)


def _make_end_call_tool(on_end_call) -> RawFunctionTool:
    async def _call(raw_arguments: dict[str, Any], context: RunContext) -> str:
        await on_end_call()
        return "Call ended."

    return function_tool(
        _call,
        raw_schema={
            "name": "end_call",
            "description": "End the phone call politely. Use this once the conversation is "
            "naturally finished or the caller asks to hang up.",
            "parameters": {"type": "object", "properties": {}},
        },
    )


def _make_transfer_call_tool(tool_def: dict[str, Any], on_transfer) -> RawFunctionTool:
    transfer_to = tool_def.get("config", {}).get("transfer_to", "")

    async def _call(raw_arguments: dict[str, Any], context: RunContext) -> str:
        await on_transfer(transfer_to)
        return f"Transferring the call to {transfer_to}."

    return function_tool(
        _call,
        raw_schema={
            "name": "transfer_call",
            "description": "Transfer the caller to a human agent when they ask for one or "
            "the request is outside what you can help with.",
            "parameters": {"type": "object", "properties": {}},
        },
    )


def _make_send_dtmf_tool(on_send_dtmf) -> RawFunctionTool:
    async def _call(raw_arguments: dict[str, Any], context: RunContext) -> str:
        digits = str(raw_arguments.get("digits", ""))
        await on_send_dtmf(digits)
        return f"Sent DTMF tones: {digits}."

    return function_tool(
        _call,
        raw_schema={
            "name": "send_dtmf",
            "description": "Press touch-tone (DTMF) keys on the call, e.g. to navigate an "
            "automated phone menu or enter an extension. digits may contain 0-9, * and #.",
            "parameters": {
                "type": "object",
                "properties": {
                    "digits": {
                        "type": "string",
                        "description": "The digits to press, in order, e.g. '1' or '4155551234#'.",
                    }
                },
                "required": ["digits"],
            },
        },
    )


def _make_lookup_knowledge_tool(on_lookup_knowledge) -> RawFunctionTool:
    async def _call(raw_arguments: dict[str, Any], context: RunContext) -> str:
        query = str(raw_arguments.get("query", ""))
        chunks = await on_lookup_knowledge(query)
        if not chunks:
            return "No relevant information found in the knowledge base."
        return "\n\n".join(chunks)

    return function_tool(
        _call,
        raw_schema={
            "name": "lookup_knowledge",
            "description": "Search the knowledge base for information relevant to the "
            "caller's question before answering — use this whenever the caller asks "
            "something that might be covered by uploaded documents (policies, pricing, "
            "product details, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, phrased as the caller's question "
                        "or its key terms.",
                    }
                },
                "required": ["query"],
            },
        },
    )


def build_tools(
    tool_defs: list[dict[str, Any]],
    *,
    on_end_call,
    on_transfer,
    on_send_dtmf,
    on_lookup_knowledge,
    http_client: httpx.AsyncClient,
    resolved_tools: list[dict[str, Any]] | None = None,
    dynamic_ctx: dict[str, str] | None = None,
) -> tuple[list[RawFunctionTool], dict[str, dict[str, Any]]]:
    """Turns an agent's `tools` jsonb config into livekit-agents function
    tools. resolved_tools (from BOLApiClient.get_agent_tools) backs any
    `tool_ref` entry in tool_defs, keyed by id.

    Returns (tools, pre_speech_by_name) — the latter lets agent.py look up
    each tool's configured pre-tool speech by its LLM-visible function name
    when a tool_call_started event fires.
    """
    resolved_by_id = {t["id"]: t for t in (resolved_tools or [])}
    dynamic_ctx = dynamic_ctx or {}

    tools: list[RawFunctionTool] = []
    pre_speech_by_name: dict[str, dict[str, Any]] = {}

    for tool_def in tool_defs:
        tool_type = tool_def.get("type")
        if tool_type == "tool_ref":
            if not tool_def.get("enabled", True):
                continue
            resolved = resolved_by_id.get(tool_def.get("tool_id"))
            if resolved is None:
                logger.warning(
                    "tool_ref %s has no matching Tool row, skipping", tool_def.get("tool_id")
                )
                continue
            tools.append(
                _make_resolved_tool(resolved, client=http_client, dynamic_ctx=dynamic_ctx)
            )
            pre_speech_by_name[resolved["name"]] = (
                resolved.get("pre_tool_speech") or {"mode": "none"}
            )
        elif tool_type == "webhook":
            tools.append(_make_webhook_tool(tool_def, http_client))
        elif tool_type == "end_call" and tool_def.get("enabled", True):
            tools.append(_make_end_call_tool(on_end_call))
        elif tool_type == "transfer_call" and tool_def.get("enabled", True):
            tools.append(_make_transfer_call_tool(tool_def, on_transfer))
        elif tool_type == "send_dtmf" and tool_def.get("enabled", True):
            tools.append(_make_send_dtmf_tool(on_send_dtmf))
        elif tool_type == "lookup_knowledge" and tool_def.get("enabled", True):
            tools.append(_make_lookup_knowledge_tool(on_lookup_knowledge))
        else:
            logger.warning("Unknown or disabled tool config, skipping: %s", tool_def)

    return tools, pre_speech_by_name
