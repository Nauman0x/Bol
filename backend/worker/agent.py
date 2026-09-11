"""LiveKit Agents worker process for Bol.

Entry point: `python -m worker.agent dev` (or `start` for production) from backend/.

The worker is a stateless process dispatched per-call by LiveKit, using the
"bol-agent" agent_name that backend/app/services/livekit_service.py bakes into the
dispatch token's RoomAgentDispatch. It never talks to the database directly --
all state reads/writes go through worker.api_client, which calls the FastAPI
backend's /internal/* routes.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli

from worker import api_client, pipeline

logger = logging.getLogger("bol-worker")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

AGENT_NAME = "bol-agent"


class BolAgent(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(instructions=instructions)


def _fire_and_forget(coro) -> None:
    """Report events/status without blocking or crashing the call on failure."""

    async def _run() -> None:
        try:
            await coro
        except Exception:
            logger.exception("background api_client call failed")

    asyncio.create_task(_run())


def _report_event(call_id: str, event_type: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(api_client.report_event(call_id, event_type, payload))


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    # Dispatch metadata is a JSON string shaped like {"call_id": "...", "agent_id": "..."}
    # -- see create_agent_dispatch_token() in app/services/livekit_service.py.
    metadata = json.loads(ctx.job.metadata or "{}")
    call_id = metadata["call_id"]
    agent_id = metadata["agent_id"]

    ctx.log_context_fields = {"call_id": call_id, "agent_id": agent_id, "room": ctx.room.name}

    agent_record = await api_client.get_agent_config(agent_id)
    config: dict[str, Any] = agent_record["config"]
    max_duration_sec = config.get("max_call_duration_sec", 300)

    vad = pipeline.build_vad()
    stt = pipeline.build_stt(config)
    llm = pipeline.build_llm(config)
    tts = pipeline.build_tts(config)
    instructions = pipeline.build_instructions(config)

    session = AgentSession(vad=vad, stt=stt, llm=llm, tts=tts)

    state: dict[str, Any] = {"completed": False, "duration_task": None}
    start_time = time.monotonic()

    async def finish_call(end_reason: str) -> None:
        if state["completed"]:
            return
        state["completed"] = True
        duration_task = state["duration_task"]
        if duration_task is not None and not duration_task.done():
            duration_task.cancel()
        duration_sec = int(time.monotonic() - start_time)
        _report_event(call_id, "status", {"state": "ended", "end_reason": end_reason})
        try:
            await api_client.complete_call(call_id, duration_sec, end_reason)
        except Exception:
            logger.exception("failed to report call completion for call_id=%s", call_id)
        ctx.shutdown(reason=end_reason)

    async def enforce_max_duration() -> None:
        await asyncio.sleep(max_duration_sec)
        logger.info("call_id=%s reached max_call_duration_sec=%s", call_id, max_duration_sec)
        await finish_call("max_duration_reached")

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: Any) -> None:
        if not getattr(ev, "is_final", True):
            return
        _report_event(
            call_id,
            "transcript_user",
            {"text": ev.transcript, "language": getattr(ev, "language", None)},
        )

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: Any) -> None:
        item = ev.item
        if getattr(item, "role", None) != "assistant":
            return
        _report_event(call_id, "transcript_agent", {"text": item.text_content})

    @session.on("close")
    def _on_close(_ev: Any) -> None:
        _fire_and_forget(finish_call("participant_disconnected"))

    await session.start(agent=BolAgent(instructions=instructions), room=ctx.room)
    await ctx.connect()

    _report_event(call_id, "status", {"state": "connected"})
    state["duration_task"] = asyncio.create_task(enforce_max_duration())

    greeting = config.get("greeting", "Hello, how can I help you today?")
    if tts is not None:
        await session.say(text=greeting)
    else:
        await session.say(text=greeting, audio=pipeline.synthesize_placeholder_audio(greeting))
    _report_event(call_id, "transcript_agent", {"text": greeting})

    if stt is None or llm is None:
        # Stub mode: no real conversation loop (no STT feeding the LLM), so
        # speak one canned reply to demonstrate the pipeline seam and stop there.
        await asyncio.sleep(2)
        reply = pipeline.STUB_REPLY
        if tts is not None:
            await session.say(text=reply)
        else:
            await session.say(text=reply, audio=pipeline.synthesize_placeholder_audio(reply))
        _report_event(call_id, "transcript_agent", {"text": reply})


if __name__ == "__main__":
    cli.run_app(server)
