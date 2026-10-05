import uuid

from httpx import ASGITransport

from app.config import settings
from app.models.call import Call, CallDirection, CallStatus
from tests.conftest import register_and_login
from worker.api_client import EventReporter, BOLApiClient
from worker.tools import build_tools

AGENT_PAYLOAD = {
    "name": "BOL Receptionist",
    "config": {
        "system_prompt": "You are a helpful receptionist.",
        "greeting": "Hi there",
        "language": "en",
        "voice_id": "default",
        "llm_model": "qwen/qwen3.6-27b",
        "temperature": 0.7,
        "max_call_duration_sec": 600,
        "interruption_enabled": True,
    },
    "tools": [],
}


def _worker_client(app) -> BOLApiClient:
    return BOLApiClient(
        base_url="http://test",
        token=settings.internal_service_token,
        transport=ASGITransport(app=app),
    )


async def test_worker_client_fetches_agent_config_from_real_api(app, client):
    headers = await register_and_login(client, "Acme", "workerclient@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    worker_client = _worker_client(app)
    config_response = await worker_client.get_agent_config(agent_id)
    assert config_response["config"]["greeting"] == "Hi there"
    await worker_client.aclose()


async def test_worker_client_reports_events_and_completes_call(app, client, db_session_factory):
    headers = await register_and_login(client, "Acme", "workerevents@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()

    async with db_session_factory() as session:
        call = Call(
            org_id=uuid.UUID(agent["org_id"]),
            agent_id=uuid.UUID(agent["id"]),
            direction=CallDirection.outbound,
            to_number="+15551234567",
            from_number="+15557654321",
            status=CallStatus.in_progress,
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = str(call.id)

    worker_client = _worker_client(app)
    reporter = EventReporter(worker_client, call_id, flush_interval_sec=1000)
    reporter.report("transcript_user", {"text": "Hi, I'd like to book an appointment."})
    reporter.report("transcript_agent", {"text": "Sure, what day works for you?"})
    await reporter._flush()  # avoid waiting on the real interval in a test

    await worker_client.complete_call(call_id, duration_sec=17, end_reason="caller_hangup")
    await worker_client.aclose()

    async with db_session_factory() as session:
        events_result = await session.get(Call, uuid.UUID(call_id))
        assert events_result.status == CallStatus.completed
        assert events_result.duration_sec == 17


async def test_event_reporter_with_no_call_id_never_calls_api():
    class ExplodingClient:
        async def report_events(self, *args, **kwargs):
            raise AssertionError("should never be called when call_id is None")

    reporter = EventReporter(ExplodingClient(), call_id=None)
    reporter.report("transcript_user", {"text": "hello"})
    await reporter._flush()  # no exception means the no-op path worked


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


class FakeHttpxClient:
    """Stand-in for a shared httpx.AsyncClient used to unit-test the webhook
    tool without a real HTTP call — build_tools now takes this client
    directly (http_client=...) rather than the tool constructing its own
    per-call, so tests pass it in instead of monkeypatching the constructor."""

    def __init__(self, response_text="ok", raise_error=False):
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls = []

    async def post(self, url, json, timeout=None):
        self.calls.append((url, json))
        if self.raise_error:
            import httpx

            raise httpx.ConnectError("boom")
        return FakeResponse(self.response_text)

    async def get(self, url, params, timeout=None):
        return await self.post(url, params, timeout=timeout)


async def test_webhook_tool_calls_configured_url():
    fake_client = FakeHttpxClient(response_text='{"slot": "3pm"}')

    tools, _pre_speech = build_tools(
        [
            {
                "type": "webhook",
                "name": "check_availability",
                "description": "Check appointment availability",
                "url": "https://example.com/availability",
                "method": "POST",
                "params_schema": {
                    "type": "object",
                    "properties": {"date": {"type": "string"}},
                    "required": ["date"],
                },
            }
        ],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=lambda _q: [],
        http_client=fake_client,
    )
    assert len(tools) == 1

    result = await tools[0](raw_arguments={"date": "2026-08-20"})
    assert result == '{"slot": "3pm"}'
    assert fake_client.calls == [("https://example.com/availability", {"date": "2026-08-20"})]


async def test_webhook_tool_handles_connection_error():
    fake_client = FakeHttpxClient(raise_error=True)

    tools, _pre_speech = build_tools(
        [
            {
                "type": "webhook",
                "name": "flaky_tool",
                "description": "A tool whose backend is down",
                "url": "https://example.com/down",
            }
        ],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=lambda _q: [],
        http_client=fake_client,
    )

    result = await tools[0](raw_arguments={})
    assert "unavailable" in result


async def test_end_call_and_transfer_tools_invoke_callbacks():
    end_call_invoked = []
    transfer_invoked = []

    async def on_end_call():
        end_call_invoked.append(True)

    async def on_transfer(transfer_to):
        transfer_invoked.append(transfer_to)

    tools, _pre_speech = build_tools(
        [
            {"type": "end_call", "enabled": True},
            {"type": "transfer_call", "enabled": True, "config": {"transfer_to": "+15550001111"}},
        ],
        on_end_call=on_end_call,
        on_transfer=on_transfer,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=lambda _q: [],
        http_client=None,
    )
    assert len(tools) == 2

    await tools[0](raw_arguments={}, context=None)
    assert end_call_invoked == [True]

    await tools[1](raw_arguments={}, context=None)
    assert transfer_invoked == ["+15550001111"]


async def test_send_dtmf_tool_invokes_callback_with_digits():
    sent = []

    async def on_send_dtmf(digits):
        sent.append(digits)

    tools, _pre_speech = build_tools(
        [{"type": "send_dtmf", "enabled": True}],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=on_send_dtmf,
        on_lookup_knowledge=lambda _q: [],
        http_client=None,
    )
    assert len(tools) == 1

    result = await tools[0](raw_arguments={"digits": "123#"}, context=None)
    assert sent == ["123#"]
    assert "123#" in result


async def test_lookup_knowledge_tool_invokes_callback_and_joins_chunks():
    async def on_lookup_knowledge(query):
        assert query == "refund policy"
        return ["Refunds are processed within 5 business days.", "Store credit is also offered."]

    tools, _pre_speech = build_tools(
        [{"type": "lookup_knowledge", "enabled": True}],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=on_lookup_knowledge,
        http_client=None,
    )
    assert len(tools) == 1

    result = await tools[0](raw_arguments={"query": "refund policy"}, context=None)
    assert "Refunds are processed" in result
    assert "Store credit" in result


async def test_lookup_knowledge_tool_handles_no_results():
    async def on_lookup_knowledge(query):
        return []

    tools, _pre_speech = build_tools(
        [{"type": "lookup_knowledge", "enabled": True}],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=on_lookup_knowledge,
        http_client=None,
    )

    result = await tools[0](raw_arguments={"query": "anything"}, context=None)
    assert "No relevant information" in result


async def test_disabled_and_unknown_tools_are_skipped():
    tools, _pre_speech = build_tools(
        [
            {"type": "end_call", "enabled": False},
            {"type": "something_unknown"},
        ],
        on_end_call=lambda: None,
        on_transfer=lambda _to: None,
        on_send_dtmf=lambda _digits: None,
        on_lookup_knowledge=lambda _q: [],
        http_client=None,
    )
    assert tools == []


def _resolved_tool(**overrides) -> dict:
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "check_availability",
        "description": "Check appointment availability",
        "is_active": True,
        "url": "https://example.com/availability",
        "method": "POST",
        "params": [
            {
                "name": "date",
                "location": "body",
                "type": "string",
                "required": True,
                "source": "llm",
            }
        ],
        "headers": [],
        "timeout_sec": 5.0,
        "retry_on_failure": False,
        "blocking": True,
        "pre_tool_speech": {"mode": "none", "phrase": ""},
        "response_extract": [],
        "resolved_headers": {},
    }
    base.update(overrides)
    return base


async def test_tool_ref_calls_resolved_tool_with_resolved_headers():
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"slot": "3pm"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as fake_client:
        tools, pre_speech = build_tools(
            [
                {
                    "type": "tool_ref",
                    "tool_id": "11111111-1111-1111-1111-111111111111",
                    "enabled": True,
                }
            ],
            on_end_call=lambda: None,
            on_transfer=lambda _to: None,
            on_send_dtmf=lambda _digits: None,
            on_lookup_knowledge=lambda _q: [],
            http_client=fake_client,
            resolved_tools=[
                _resolved_tool(resolved_headers={"Authorization": "Bearer sk-test"})
            ],
            dynamic_ctx={
                "call_id": "c1",
                "agent_id": "a1",
                "org_id": "o1",
                "caller_number": "",
                "to_number": "",
                "direction": "outbound",
                "transport": "telephony",
                "now_iso": "2026-08-22T00:00:00+00:00",
            },
        )
        assert len(tools) == 1
        assert "check_availability" in pre_speech

        result = await tools[0](raw_arguments={"date": "2026-08-20"})
        assert result == '{"slot": "3pm"}' or "3pm" in result
        assert captured["auth"] == "Bearer sk-test"


async def test_tool_ref_missing_required_arg_returns_speakable_error():
    import httpx

    async with httpx.AsyncClient() as fake_client:
        tools, _pre_speech = build_tools(
            [
                {
                    "type": "tool_ref",
                    "tool_id": "11111111-1111-1111-1111-111111111111",
                    "enabled": True,
                }
            ],
            on_end_call=lambda: None,
            on_transfer=lambda _to: None,
            on_send_dtmf=lambda _digits: None,
            on_lookup_knowledge=lambda _q: [],
            http_client=fake_client,
            resolved_tools=[_resolved_tool()],
            dynamic_ctx={},
        )
        result = await tools[0](raw_arguments={})
        assert "failed" in result
        assert "date" in result


async def test_non_blocking_tool_returns_immediately_before_request_completes():
    import asyncio

    import httpx

    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as fake_client:
        tools, _pre_speech = build_tools(
            [
                {
                    "type": "tool_ref",
                    "tool_id": "11111111-1111-1111-1111-111111111111",
                    "enabled": True,
                }
            ],
            on_end_call=lambda: None,
            on_transfer=lambda _to: None,
            on_send_dtmf=lambda _digits: None,
            on_lookup_knowledge=lambda _q: [],
            http_client=fake_client,
            resolved_tools=[_resolved_tool(blocking=False)],
            dynamic_ctx={},
        )

        result = await asyncio.wait_for(tools[0](raw_arguments={"date": "2026-08-20"}), timeout=1.0)
        assert result == "Request sent."
        release.set()
        await asyncio.wait_for(started.wait(), timeout=1.0)
