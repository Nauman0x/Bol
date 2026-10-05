"""LiveKit Agents entrypoint — the BOL voice agent (docs/PLAN.md Phase 3).

Stateless by design: the worker never opens a DB connection. It reads
{call_id, agent_id, transport} from LiveKit job dispatch metadata, fetches
the agent's config over HTTP from the API, and reports transcript/tool/status
events back the same way. That statelessness is what lets worker processes
autoscale independently of the API.

Run with:
    python -m worker.agent dev     # connect to LiveKit Cloud, print logs locally
    python -m worker.agent start   # production worker process
"""

import asyncio
import json
import logging
import random
from pathlib import Path

import httpx
from livekit import api as lk_api
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
)

from app.config import settings
from app.services.tool_executor import build_dynamic_context
from app.tts_providers import resolve_llm_model, resolve_tts_provider
from worker import ambience
from worker.api_client import EventReporter, BOLApiClient
from worker.interruption import BargeInTracker
from worker.latency import LatencyCollector
from worker.pipeline import (
    build_background_audio,
    build_instructions,
    build_llm,
    build_noise_cancellation,
    build_stt,
    build_tts,
    build_turn_handling,
    build_vad,
)
from worker.tools import build_tools

logger = logging.getLogger("BOL.worker")

GOODBYE_TEXT = (
    "We're at the time limit for this call, so I have to go now. "
    "Thank you for calling, goodbye!"
)

# RFC 4733 DTMF event codes — 0-9 map to themselves, then '*'/'#', then A-D
# (rarely used outside carrier signaling, included for completeness).
_DTMF_DIGIT_TO_CODE = {
    **{str(i): i for i in range(10)},
    "*": 10,
    "#": 11,
    **{c: 12 + i for i, c in enumerate("ABCD")},
}

# Only languages with a genuine translation get an entry — an agent whose
# language isn't listed here gets no spoken filler at all (see
# _on_tool_execution below) rather than an English phrase blurted mid-call
# in a non-English conversation.
_FILLER_PHRASES = {
    "en": ["One moment.", "Let me check on that.", "Just a second."],
    "ar": ["لحظة من فضلك.", "دعني أتحقق من ذلك."],
    "es": ["Un momento.", "Déjame revisar eso.", "Un segundo."],
    "fr": ["Un instant.", "Laissez-moi vérifier.", "Une seconde."],
    "de": ["Einen Moment.", "Lassen Sie mich das prüfen.", "Eine Sekunde."],
    "hi": ["एक क्षण।", "मुझे यह देखने दें।"],
    "ur": ["ایک لمحہ۔", "مجھے یہ چیک کرنے دیں۔"],
    "pt": ["Um momento.", "Deixe-me verificar isso.", "Um segundo."],
    "ru": ["Один момент.", "Дайте мне проверить это."],
    "zh": ["请稍等。", "让我查一下。"],
}

# LiveKit's SIP bridge sets these attributes on SIP participants. Confirmed
# against the installed livekit-agents source: "sip.ruleID" and
# "sip.callStatus" are used the same way by the framework's own AMD code
# (voice/amd/detector.py), which gates all audio/transcript processing on
# sip.callStatus == "active" for exactly the reason _wait_until_answered
# below exists — ringback/carrier early media/dialtone must not reach STT.
# The trunk/caller number attributes follow the same "sip.*" convention but
# were NOT independently confirmed against a live inbound call in this
# environment (no real SIP trunk available) — verify before relying on this
# in production; see docs/TELEPHONY_SETUP.md.
_SIP_ATTR_TRUNK_PHONE_NUMBER = "sip.trunkPhoneNumber"
_SIP_ATTR_CALLER_PHONE_NUMBER = "sip.phoneNumber"
_SIP_ATTR_CALL_STATUS = "sip.callStatus"
_SIP_CALL_STATUS_ACTIVE = "active"
_INBOUND_SIP_WAIT_TIMEOUT_SEC = 15.0
_ANSWER_WAIT_TIMEOUT_SEC = 45.0


class BOLAgent(Agent):
    """Speaks a short acknowledgment when the caller's just-committed turn
    was a genuine interruption of the agent — see worker/interruption.py for
    why this has to happen here (on_user_turn_completed, after the
    interrupted handle is resolved and before the reply is scheduled) rather
    than at interrupt time, when the caller is still talking."""

    def __init__(self, *, barge_in: BargeInTracker, on_ack, **kwargs) -> None:
        super().__init__(**kwargs)
        self._barge_in = barge_in
        self._on_ack = on_ack

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        # Must not raise (would silently drop the reply this turn — see
        # agent_activity.py's on_user_turn_completed caller) and must not
        # await session.say() (it would block the scheduler waiting on this
        # coroutine and delay the real reply behind the ack's full playout
        # instead of just queuing behind it).
        try:
            phrase = self._barge_in.take_ack()
            if phrase:
                self.session.say(phrase, allow_interruptions=True, add_to_chat_ctx=False)
                self._on_ack()
        except Exception:
            logger.exception("barge-in acknowledgment failed")


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process and reused across calls — VAD model load is
    # too slow to repeat per job.
    proc.userdata["vad"] = build_vad()


async def _resolve_inbound_call(ctx: JobContext, api: BOLApiClient) -> tuple[str, str] | None:
    """No agent_id in job metadata means this job was dispatched by a LiveKit SIP
    dispatch rule for an inbound call, not by our own /calls/outbound. Find the
    called/caller numbers from the SIP participant and create the call row.
    Returns (call_id, agent_id) as strings, or None if resolution failed.
    """
    try:
        participant = await asyncio.wait_for(
            ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP),
            timeout=_INBOUND_SIP_WAIT_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.error("No SIP participant joined room %s within timeout", ctx.room.name)
        return None

    to_number = participant.attributes.get(_SIP_ATTR_TRUNK_PHONE_NUMBER)
    from_number = participant.attributes.get(_SIP_ATTR_CALLER_PHONE_NUMBER)
    if not to_number:
        logger.error(
            "SIP participant %s missing %s attribute; attributes=%r",
            participant.identity,
            _SIP_ATTR_TRUNK_PHONE_NUMBER,
            participant.attributes,
        )
        return None

    try:
        created = await api.create_inbound_call(
            to_number=to_number,
            from_number=from_number or "unknown",
            livekit_room_name=ctx.room.name,
        )
    except Exception:
        logger.exception("Failed to create inbound call row for to_number=%s", to_number)
        return None

    return str(created["call_id"]), str(created["agent_id"])


async def _wait_until_answered(ctx: JobContext, timeout: float = _ANSWER_WAIT_TIMEOUT_SEC) -> bool:
    """Outbound telephony only. Blocks until the callee's SIP leg reports
    sip.callStatus == "active" before this function's caller ever calls
    session.start() — so RoomIO never attaches to the room's audio while
    it's still ringback/dialtone/early media, and the greeting can't be
    spoken into it either. Returns True once answered, False on timeout
    (never picked up).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    try:
        participant = await asyncio.wait_for(
            ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP),
            timeout=max(deadline - loop.time(), 0),
        )
    except TimeoutError:
        return False

    if participant.attributes.get(_SIP_ATTR_CALL_STATUS) == _SIP_CALL_STATUS_ACTIVE:
        return True

    answered = asyncio.Event()

    def _on_attrs_changed(changed_attributes: dict, p: rtc.RemoteParticipant) -> None:
        if p.sid == participant.sid and changed_attributes.get(_SIP_ATTR_CALL_STATUS) == (
            _SIP_CALL_STATUS_ACTIVE
        ):
            answered.set()

    ctx.room.on("participant_attributes_changed", _on_attrs_changed)
    try:
        await asyncio.wait_for(answered.wait(), timeout=max(deadline - loop.time(), 0))
        return True
    except TimeoutError:
        return False
    finally:
        ctx.room.off("participant_attributes_changed", _on_attrs_changed)


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    job_metadata: dict = {}
    if ctx.job.metadata:
        try:
            job_metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.error("Job metadata is not valid JSON: %r", ctx.job.metadata)

    agent_id = job_metadata.get("agent_id")
    call_id = job_metadata.get("call_id")
    # Every dispatch we create sets this (see app/services/livekit_service.py);
    # "telephony" is a safe default for the (unexpected) case it's missing,
    # since that only skips the answer-wait rather than mis-starting one.
    transport = job_metadata.get("transport", "telephony")

    api = BOLApiClient()

    is_inbound = not agent_id
    if is_inbound:
        # No metadata from our own dispatch — this is an inbound SIP call.
        # Always telephony; inbound never carries job metadata at all.
        transport = "telephony"
        resolved = await _resolve_inbound_call(ctx, api)
        if resolved is None:
            await api.aclose()
            ctx.shutdown(reason="inbound call resolution failed")
            return
        call_id, agent_id = resolved

    reporter = EventReporter(api, call_id)

    try:
        agent_config_response = await api.get_agent_config(agent_id)
    except Exception:
        logger.exception("Failed to fetch agent config for agent_id=%s", agent_id)
        await api.aclose()
        ctx.shutdown(reason="agent config fetch failed")
        return

    config = agent_config_response["config"]
    tools_config = agent_config_response.get("tools", [])
    try:
        resolved_tools = await api.get_agent_tools(agent_id)
    except Exception:
        logger.exception(
            "Failed to fetch tools for agent_id=%s — proceeding without them", agent_id
        )
        resolved_tools = []
    # caller_number/to_number aren't threaded through job dispatch metadata
    # today (see _resolve_inbound_call for inbound, app/services/
    # livekit_service.py for outbound) — a Tool's `dynamic` params can still
    # reference them, they just resolve to "" until that's wired up.
    dynamic_ctx = build_dynamic_context(
        call_id=call_id or "",
        agent_id=agent_id or "",
        org_id=agent_config_response.get("org_id", ""),
        direction="inbound" if is_inbound else "outbound",
        transport=transport,
    )

    resolved_tts_provider = resolve_tts_provider(config)
    resolved_llm_model = resolve_llm_model(config)

    # Kicked off now (in parallel with the rest of session setup below, and
    # with any answer-wait for outbound telephony) rather than after the
    # greeting, so a custom ambience clip has the longest possible window to
    # download before it's needed.
    ambience_task = ambience.start_prefetch(api, config)

    http_client = httpx.AsyncClient()
    latency = LatencyCollector()

    # --- Everything below this point is cleaned up by _cleanup, registered
    # immediately after — so every one of these names must exist (even as a
    # placeholder) before that registration, not just by the time _cleanup
    # actually runs. This is what fixes the old bug where anything throwing
    # between here and the end of the function leaked the API client and the
    # http client, and left the call stuck non-terminal forever (permanently
    # consuming an org's concurrency slot — see calls.py's _reap_stale_calls,
    # which exists to clean up the cases that still slip through, e.g. a
    # killed process that never runs shutdown callbacks at all).
    duration_task: asyncio.Task | None = None
    background_audio = None
    end_reason = "completed"
    egress_id: str | None = None
    recording_key: str | None = None
    record_locally = False
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    answer_time = start_time

    async def _cleanup() -> None:
        if duration_task is not None:
            duration_task.cancel()
        if background_audio is not None:
            await background_audio.aclose()
        if egress_id is not None:
            try:
                await ctx.api.egress.stop_egress(lk_api.StopEgressRequest(egress_id=egress_id))
            except Exception:
                logger.exception("Failed to stop egress %s for call %s", egress_id, call_id)
        if record_locally and call_id:
            recording_path = Path(ctx.session_directory) / "audio.ogg"
            try:
                if recording_path.exists():
                    await api.upload_recording(
                        call_id, recording_path.read_bytes(), "audio/ogg"
                    )
            except Exception:
                logger.exception("Failed to upload local recording for call %s", call_id)
        await http_client.aclose()
        duration_sec = int(loop.time() - answer_time)
        await reporter.stop_and_flush()
        if call_id:
            summary = latency.summary()
            avg_ms, p95_ms = latency.headline_ms()
            await api.complete_call(
                call_id,
                duration_sec,
                end_reason,
                transport=transport,
                tts_provider=resolved_tts_provider,
                llm_model=resolved_llm_model,
                latency_stats=summary,
                avg_latency_ms=avg_ms,
                p95_latency_ms=p95_ms,
                recording_key=recording_key,
            )
        await api.aclose()

    ctx.add_shutdown_callback(_cleanup)

    try:
        tts = build_tts(config)
    except Exception:
        # A misconfigured/unsupported TTS provider (e.g. CHATTERBOX_BASE_URL
        # unset while an agent is set to tts_provider=chatterbox) used to
        # raise straight out of entrypoint here — the job died, but the
        # browser was already connected to the room, so a test call just sat
        # silent forever with nothing to explain why. _cleanup (registered
        # above) still runs after shutdown() and reports this end_reason.
        logger.exception("Failed to build TTS provider for agent_id=%s", agent_id)
        end_reason = "tts_init_failed"
        ctx.shutdown(reason="tts init failed")
        return

    turn_handling = build_turn_handling(config)
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=build_stt(config),
        llm=build_llm(config),
        tts=tts,
        # See worker/pipeline.py:build_turn_handling for the endpointing/
        # interruption/preemptive-generation tuning rationale.
        turn_handling=turn_handling,
    )
    latency.set_interruption_config(
        config.get("interruption_style", "balanced"), turn_handling["interruption"]["mode"]
    )
    if (
        config.get("interruption_mode", "vad") == "adaptive"
        and turn_handling["interruption"]["mode"] != "adaptive"
    ):
        # build_turn_handling already downgraded and logged this — also put
        # it on the call timeline, since the worker log isn't something a
        # customer (or most operators) would ever go looking at.
        reporter.report(
            "status",
            {
                "event": "adaptive_interruption_unavailable",
                "reason": (
                    f"STT_PROVIDER={settings.stt_provider} doesn't support adaptive "
                    "interruption detection; used vad instead"
                ),
            },
        )

    barge_in = BargeInTracker(
        enabled=config.get("ack_on_interrupt", False), language=config.get("language", "en")
    )
    # SpeechHandles that should never get a barge-in ack even if the caller
    # talks over them — the greeting and any tool filler have their own
    # framing and acking them would be redundant or confusing. Populated
    # below as those handles are created.
    _unackable_handles: set = set()
    resume_style = config.get("resume_style", "instant")
    _connector_count = 0
    _last_connector_at: float | None = None
    _CONNECTOR_MAX_PER_CALL = 2
    _CONNECTOR_COOLDOWN_SEC = 10.0
    _CONNECTOR_INSTRUCTIONS = (
        "The caller briefly interrupted you but it turned out to be nothing "
        "(a cough, a filler word, background noise) — you are resuming the "
        "answer you were giving. Re-enter naturally with a brief acknowledgment "
        "in the caller's own language (the equivalent of \"Sorry, as I was "
        "saying —\") before continuing your point. Do not restate what you "
        "already said."
    )

    call_ended = asyncio.Event()

    async def _end_call(reason: str = "agent_ended_call") -> None:
        nonlocal end_reason
        end_reason = reason
        session.shutdown()

    async def _transfer_call(transfer_to: str) -> None:
        sip_participant = next(
            (
                p
                for p in ctx.room.remote_participants.values()
                if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            ),
            None,
        )
        if sip_participant is None:
            logger.error("transfer_call requested but no SIP participant found in room")
            reporter.report(
                "error", {"message": "transfer_call failed: no SIP participant in room"}
            )
            return
        try:
            await ctx.transfer_sip_participant(sip_participant, transfer_to)
        except Exception:
            logger.exception("SIP transfer to %s failed", transfer_to)
            reporter.report("error", {"message": f"transfer_call to {transfer_to} failed"})
            return
        await _end_call(reason="transferred")

    async def _send_dtmf(digits: str) -> None:
        for digit in digits:
            code = _DTMF_DIGIT_TO_CODE.get(digit.upper())
            if code is None:
                logger.warning("send_dtmf: skipping unsupported digit %r", digit)
                continue
            try:
                await ctx.room.local_participant.publish_dtmf(code=code, digit=digit)
            except Exception:
                logger.exception("send_dtmf: failed to publish digit %r", digit)
                reporter.report("error", {"message": f"send_dtmf failed on digit {digit!r}"})
                return
            # A brief gap between tones — sending them back-to-back with no
            # delay is how carriers drop or merge digits on the receiving IVR.
            await asyncio.sleep(0.15)

    async def _lookup_knowledge(query: str) -> list[str]:
        try:
            return await api.search_knowledge(agent_config_response["org_id"], query)
        except Exception:
            logger.exception("lookup_knowledge failed for query %r", query)
            return []

    tools, pre_speech_by_name = build_tools(
        tools_config,
        on_end_call=lambda: _end_call("agent_ended_call"),
        on_transfer=_transfer_call,
        on_send_dtmf=_send_dtmf,
        on_lookup_knowledge=_lookup_knowledge,
        http_client=http_client,
        resolved_tools=resolved_tools,
        dynamic_ctx=dynamic_ctx,
    )

    agent = BOLAgent(
        barge_in=barge_in,
        on_ack=lambda: latency.record_interruption("acked"),
        instructions=build_instructions(config, tts.capabilities.streaming),
        tools=tools,
    )

    @session.on("user_state_changed")
    def _on_user_state_changed_barge_in(event) -> None:
        if event.new_state != "speaking":
            return
        barge_in.arm(
            agent_speaking=session.agent_state == "speaking",
            current_handle=session.current_speech,
            excluded_handles=frozenset(_unackable_handles),
        )

    @session.on("agent_state_changed")
    def _on_agent_state_changed_barge_in(event) -> None:
        if event.new_state == "speaking":
            # A new agent turn started — any latch armed against the
            # previous turn's speech is stale.
            barge_in.disarm()

    @session.on("agent_false_interruption")
    def _on_false_interruption(event) -> None:
        nonlocal _connector_count, _last_connector_at
        barge_in.disarm()
        resumed = bool(getattr(event, "resumed", False))
        latency.record_interruption("resumed" if resumed else "false")
        reporter.report("status", {"event": "false_interruption", "resumed": resumed})
        if not resumed or resume_style != "connector":
            return
        now = loop.time()
        if _connector_count >= _CONNECTOR_MAX_PER_CALL:
            return
        if _last_connector_at is not None and now - _last_connector_at < _CONNECTOR_COOLDOWN_SEC:
            return
        _connector_count += 1
        _last_connector_at = now
        latency.record_interruption("connector")
        try:
            session.interrupt()
            session.generate_reply(instructions=_CONNECTOR_INSTRUCTIONS)
        except Exception:
            logger.exception("resume connector failed for call %s", call_id)

    @session.on("conversation_item_added")
    def _on_item_added(event) -> None:
        item = event.item
        role = getattr(item, "role", None)
        if role not in ("user", "assistant"):
            return
        if role == "assistant" and getattr(item, "interrupted", False):
            latency.record_interruption("true")
        content = getattr(item, "content", [])
        text = "".join(c if isinstance(c, str) else getattr(c, "text", "") for c in content)
        event_type = "transcript_user" if role == "user" else "transcript_agent"

        # MetricsReport (livekit.agents.llm.chat_context) — read straight off
        # the item via the shared LatencyCollector instead of hand-timing
        # anything. e2e_latency is the number that matters most: user
        # stopped speaking -> agent started responding. Recorded for every
        # turn and aggregated at call end (see _cleanup) so latency work is
        # measurable across every provider combination, not guessed at.
        metrics = getattr(item, "metrics", None) or {}
        timings = latency.record_turn(role, metrics)
        if timings:
            logger.info("turn timings (%s): %s", role, timings, extra={"timings": timings})

        payload = {"text": text}
        if timings:
            payload["timings"] = timings
        reporter.report(event_type, payload)

    @session.on("function_tools_executed")
    def _on_tools_executed(event) -> None:
        for call, output in zip(event.function_calls, event.function_call_outputs, strict=False):
            reporter.report("tool_call", {"name": call.name, "arguments": call.arguments})
            if output is not None:
                # call.created_at / output.created_at are framework-native
                # timestamps (llm/chat_context.py) bracketing "LLM decided to
                # call this tool" -> "tool finished" — reused here rather
                # than hand-rolling separate instrumentation in worker/tools.py.
                duration_ms = None
                call_created_at = getattr(call, "created_at", None)
                output_created_at = getattr(output, "created_at", None)
                if call_created_at is not None and output_created_at is not None:
                    duration_ms = round((output_created_at - call_created_at) * 1000)
                reporter.report(
                    "tool_result",
                    {
                        "name": output.name,
                        "output": output.output,
                        "is_error": output.is_error,
                        "duration_ms": duration_ms,
                    },
                )

    @session.on("error")
    def _on_pipeline_error(event) -> None:
        # STT/LLM/TTS failures (e.g. Chatterbox unreachable/timing out, or a
        # bad voice_id) land here — previously nothing was listening, so a
        # failed synthesis just resolved the speech handle with no audio and
        # left no trace anywhere (worker log, call timeline, or UI).
        logger.error(
            "Pipeline error from %s (recoverable=%s): %s",
            event.error.type,
            event.error.recoverable,
            event.error.error,
        )
        reporter.report(
            "error",
            {
                "source": event.error.type,
                "recoverable": event.error.recoverable,
                "message": str(event.error.error),
            },
        )

    @session.on("close")
    def _on_close(event) -> None:
        call_ended.set()

    # Per-tool pre-tool speech (Tool.pre_tool_speech, see app/schemas/tool.py)
    # takes priority over the agent-wide filler_phrases toggle: "fixed" says
    # that tool's own phrase, "auto" reuses the localized filler-phrase
    # behavior below, "none" stays silent even if filler_phrases is on. A
    # tool with no configured speech (builtins, or tool_refs that never set
    # one) falls back to the agent-wide toggle, matching pre-existing
    # behavior. asyncio only holds a weak reference to a task — without
    # keeping one here, a speech task can be garbage-collected mid-speech
    # since nothing else references it (documented CPython behavior).
    _tool_speech_tasks: set[asyncio.Task] = set()
    _default_speech = {"mode": "auto"} if config.get("filler_phrases", False) else {"mode": "none"}

    @session.on("tool_execution_updated")
    def _on_tool_execution(event) -> None:
        if event.update.type != "tool_call_started":
            return
        speech = pre_speech_by_name.get(event.update.function_call.name, _default_speech)
        mode = speech.get("mode", "none")
        if mode == "none":
            return
        if mode == "fixed":
            phrase = speech.get("phrase") or ""
            if not phrase:
                return
        else:  # auto
            phrases = _FILLER_PHRASES.get(config.get("language", "en"))
            if not phrases:
                # No localized filler for this language — say nothing
                # rather than blurting an English phrase mid-call.
                return
            phrase = random.choice(phrases)
        handle = session.say(phrase, allow_interruptions=True)
        _unackable_handles.add(handle)
        task = asyncio.create_task(handle)
        _tool_speech_tasks.add(task)
        task.add_done_callback(_tool_speech_tasks.discard)

    def _on_dtmf_received(dtmf: rtc.SipDTMF) -> None:
        reporter.report("status", {"event": "dtmf_received", "digit": dtmf.digit})

    ctx.room.on("sip_dtmf_received", _on_dtmf_received)

    reporter.start()

    # Outbound telephony only: block until the callee actually picks up,
    # and do it BEFORE session.start() — session.start() is what attaches
    # RoomIO to the room's audio, so waiting first means ringback/early
    # media never reaches STT, and the greeting (below) never gets spoken
    # into it either. AgentSession's own construction (above) already
    # kicked off LLM prewarming independent of session.start()
    # (agent_session.py's __init__ calls llm.prewarm()), so that benefit
    # isn't lost by waiting — only STT/TTS prewarming (which session.start()
    # triggers) is deferred, a small trade for not processing ringback as
    # if it were speech.
    if transport == "telephony" and not is_inbound:
        answered = await _wait_until_answered(ctx)
        if not answered:
            end_reason = "no_answer"
            # No conversation ever happened — duration_sec in _cleanup is
            # loop.time() - answer_time, and answer_time still defaults to
            # start_time here, so without this the full ring-wait
            # (up to _ANSWER_WAIT_TIMEOUT_SEC) would be reported as call
            # duration instead of ~0.
            answer_time = loop.time()
            if ambience_task is not None:
                ambience_task.cancel()
            logger.info("Outbound call %s never answered, ending", call_id)
            ctx.shutdown(reason="no_answer")
            return
        answer_time = loop.time()
        await api.report_answered(call_id)
    elif call_id and transport == "webrtc":
        # No ring phase for a browser test call — "answered" the moment
        # we're ready to start the session.
        answer_time = loop.time()
        await api.report_answered(call_id)
    # else: inbound telephony — already marked in_progress/answered_at at
    # Call-row creation (app/routers/internal.py:create_inbound_call), since
    # by the time our job even starts the SIP leg has already been accepted.

    # session.start() schedules AgentActivity._update_activity in the background,
    # which calls .prewarm() on the resolved STT/LLM/TTS — for Groq's LLM and TTS
    # (both extend the OpenAI plugin base classes) that fires a real token-free
    # request (models.list() / GET "/") to warm the TLS connection before the
    # caller's first turn. This is framework behavior, not something we trigger —
    # verified against the installed livekit-agents source
    # (voice/agent_activity.py, plugins/openai/{llm,tts}.py) rather than assumed.
    # No hand-rolled prewarm needed here.
    s3_configured = bool(
        settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key
    )
    # No S3 bucket configured: fall back to the SDK's own local RecorderIO
    # (mixes both audio channels to job_ctx.session_directory/audio.ogg)
    # instead of LiveKit Cloud egress, and upload the file to our own API in
    # _cleanup below once the call ends. Mutually exclusive with the egress
    # path — never record both ways for the same call.
    record_locally = bool(call_id) and not s3_configured
    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=build_noise_cancellation(transport)
        ),
        record=record_locally,
    )
    if call_id and s3_configured:
        candidate_key = f"recordings/{call_id}.ogg"
        try:
            egress_info = await ctx.api.egress.start_room_composite_egress(
                lk_api.RoomCompositeEgressRequest(
                    room_name=ctx.room.name,
                    audio_only=True,
                    file_outputs=[
                        lk_api.EncodedFileOutput(
                            file_type=lk_api.EncodedFileType.OGG,
                            filepath=candidate_key,
                            s3=lk_api.S3Upload(
                                access_key=settings.s3_access_key_id,
                                secret=settings.s3_secret_access_key,
                                region=settings.s3_region,
                                bucket=settings.s3_bucket,
                            ),
                        )
                    ],
                )
            )
            egress_id = egress_info.egress_id
            recording_key = candidate_key
        except Exception:
            # Best-effort — a failed egress start must never fail the call
            # itself, it just means this one call won't have a recording.
            logger.exception("Failed to start room-composite egress for call %s", call_id)

    greeting = config.get("greeting")
    if greeting and config.get("greeting_mode", "agent_first") == "wait_for_caller":
        # Outbound etiquette: many people answer with "Hello?" — stay silent
        # until VAD detects the callee actually said something, then greet.
        # Triggered on "speaking" (not the final transcript) so the greeting
        # doesn't lag behind a slow STT round-trip.
        _greeted = False

        def _on_user_state_changed(event) -> None:
            nonlocal _greeted
            if not _greeted and event.new_state == "speaking":
                _greeted = True
                _unackable_handles.add(session.say(greeting))
                session.off("user_state_changed", _on_user_state_changed)

        session.on("user_state_changed", _on_user_state_changed)
    elif greeting:
        _unackable_handles.add(session.say(greeting))

    # Resolved after the greeting so a slow/unreachable custom clip never
    # delays it — ambience.await_prefetch() has its own hard timeout and
    # falls back to no ambience rather than blocking. Publishes on its own
    # separate room track, so it never touches the STT/LLM/TTS latency path.
    custom_clip_path = await ambience.await_prefetch(ambience_task)
    background_audio = build_background_audio(config, custom_clip_path=custom_clip_path)
    if background_audio is not None:
        # source=SOURCE_MICROPHONE (not the default SOURCE_UNKNOWN): the
        # agent's own TTS output track publishes with this same source (see
        # the framework's RoomIO defaults), which is the convention the
        # LiveKit SIP bridge is expected to forward to the PSTN leg — an
        # unrecognized/unknown source may not be. Confirmed correct for
        # WebRTC (every track is attached regardless of source there);
        # unconfirmed against a real phone call — verify ambience is
        # actually audible on a real call before relying on this.
        await background_audio.start(
            room=ctx.room,
            agent_session=session,
            track_publish_options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )

    max_duration = config.get("max_call_duration_sec", 600)

    async def _enforce_max_duration() -> None:
        await asyncio.sleep(max_duration)
        if not call_ended.is_set():
            logger.info("Max call duration (%ss) reached, ending call", max_duration)
            # Awaited (not fire-and-forget) so the goodbye actually finishes
            # playing before session.shutdown() tears the session down —
            # previously this was cut off mid-sentence.
            await session.say(GOODBYE_TEXT, allow_interruptions=False)
            await _end_call("max_duration_reached")

    duration_task = asyncio.create_task(_enforce_max_duration())

    await call_ended.wait()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="BOL-agent",
            ws_url=settings.livekit_url or None,
            api_key=settings.livekit_api_key or None,
            api_secret=settings.livekit_api_secret or None,
        )
    )
