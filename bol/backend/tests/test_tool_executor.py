"""Unit tests for the shared tool-call resolver/executor (app/services/
tool_executor.py) — the piece both POST /tools/{id}/test and the worker's
function-tool wrapper (worker/tools.py) go through. No real network calls;
httpx.MockTransport stands in for the outbound HTTP.
"""

import httpx
import pytest

from app.schemas.tool import ResponseExtract, ToolParam
from app.services import tool_executor


def _param(**kwargs) -> ToolParam:
    return ToolParam(**{"name": "x", "location": "query", "source": "llm", **kwargs})


def test_build_llm_schema_only_includes_llm_source_params():
    params = [
        ToolParam(name="date", location="body", source="llm", required=True, description="d"),
        ToolParam(name="call_id", location="body", source="dynamic", value="call_id"),
        ToolParam(name="api_version", location="query", source="constant", value="v1"),
    ]
    schema = tool_executor.build_llm_schema("book", "Books a slot", params)
    assert schema["name"] == "book"
    assert set(schema["parameters"]["properties"]) == {"date"}
    assert schema["parameters"]["required"] == ["date"]


def test_resolve_params_merges_llm_constant_and_dynamic_sources():
    params = [
        _param(name="date", location="body", source="llm", required=True),
        _param(name="api_key", location="header", source="constant", value="abc123"),
        _param(name="call_id", location="query", source="dynamic", value="call_id"),
    ]
    url, query, body, headers = tool_executor.resolve_params(
        "https://example.com/book", params, {"date": "2026-08-20"}, {"call_id": "call_42"}
    )
    assert url == "https://example.com/book"
    assert query == {"call_id": "call_42"}
    assert body == {"date": "2026-08-20"}
    assert headers == {"api_key": "abc123"}


def test_resolve_params_missing_required_llm_arg_raises():
    params = [_param(name="date", location="body", source="llm", required=True)]
    with pytest.raises(tool_executor.ToolParamError):
        tool_executor.resolve_params("https://example.com", params, {}, {})


def test_resolve_params_unknown_dynamic_var_raises():
    params = [_param(name="x", location="query", source="dynamic", value="not_a_real_var")]
    with pytest.raises(tool_executor.ToolParamError):
        tool_executor.resolve_params("https://example.com", params, {}, {"call_id": "c1"})


def test_resolve_params_templates_path_and_quotes_values():
    params = [_param(name="booking_id", location="path", source="llm", required=True)]
    url, *_ = tool_executor.resolve_params(
        "https://example.com/bookings/{booking_id}", params, {"booking_id": "abc"}, {}
    )
    assert url == "https://example.com/bookings/abc"


def test_resolve_params_path_value_cannot_inject_new_segment():
    """A path param value containing "/" must be percent-encoded, not
    spliced in raw — otherwise a caller-controlled value could redirect the
    request to a different path (or, via "../", a different resource)."""
    params = [_param(name="booking_id", location="path", source="llm", required=True)]
    url, *_ = tool_executor.resolve_params(
        "https://example.com/bookings/{booking_id}",
        params,
        {"booking_id": "../../admin"},
        {},
    )
    assert "/../" not in url
    assert url == "https://example.com/bookings/..%2F..%2Fadmin"


def test_resolve_params_unresolved_placeholder_raises():
    # No param supplies {booking_id} at all.
    with pytest.raises(tool_executor.ToolParamError):
        tool_executor.resolve_params("https://example.com/bookings/{booking_id}", [], {}, {})


async def test_run_tool_rejects_ssrf_unsafe_resolved_url():
    async with httpx.AsyncClient() as client:
        result = await tool_executor.run_tool(
            url="https://localhost/internal",
            method="GET",
            query={},
            body={},
            headers={},
            timeout_sec=5.0,
            retry_on_failure=False,
            response_extract=[],
            client=client,
        )
    assert result.ok is False
    assert result.status_code is None
    assert "not allowed" in result.error


async def test_run_tool_success_extracts_response_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"slot": "3pm"}, "id": "abc"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tool_executor.run_tool(
            url="https://example.com/book",
            method="POST",
            query={},
            body={"date": "2026-08-20"},
            headers={},
            timeout_sec=5.0,
            retry_on_failure=False,
            response_extract=[ResponseExtract(name="slot", path="data.slot")],
            client=client,
        )
    assert result.ok is True
    assert result.status_code == 200
    assert result.extracted == {"slot": "3pm"}


async def test_run_tool_timeout_returns_speakable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tool_executor.run_tool(
            url="https://example.com/book",
            method="POST",
            query={},
            body={},
            headers={},
            timeout_sec=1.0,
            retry_on_failure=False,
            response_extract=[],
            client=client,
        )
    assert result.ok is False
    assert result.error == "the service timed out"
    # never a stack trace or raw exception text leaking to the caller
    assert "Traceback" not in (result.error or "")


async def test_run_tool_retries_once_on_5xx_then_succeeds():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tool_executor.run_tool(
            url="https://example.com/book",
            method="GET",
            query={},
            body={},
            headers={},
            timeout_sec=5.0,
            retry_on_failure=True,
            response_extract=[],
            client=client,
        )
    assert len(attempts) == 2
    assert result.ok is True


async def test_run_tool_does_not_retry_when_retry_on_failure_is_false():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tool_executor.run_tool(
            url="https://example.com/book",
            method="GET",
            query={},
            body={},
            headers={},
            timeout_sec=5.0,
            retry_on_failure=False,
            response_extract=[],
            client=client,
        )
    assert len(attempts) == 1
    assert result.ok is False


def test_extract_path_wildcard():
    from app.services.tool_response import extract_path

    data = {"results": [{"name": "a"}, {"name": "b"}]}
    assert extract_path(data, "results[*].name") == ["a", "b"]
