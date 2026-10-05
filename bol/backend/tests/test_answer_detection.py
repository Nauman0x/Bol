"""Unit tests for worker/agent.py's _wait_until_answered — the fix for
outbound calls greeting into ringback (B3). Exercised against small fake
JobContext/Room stand-ins rather than a real LiveKit connection, since
that's the only realistic way to unit-test SIP attribute-change timing.
"""

import asyncio

from worker.agent import _SIP_ATTR_CALL_STATUS, _wait_until_answered


class _FakeParticipant:
    def __init__(self, sid: str, attributes: dict):
        self.sid = sid
        self.attributes = attributes


class _FakeRoom:
    def __init__(self):
        self._listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback) -> None:
        self._listeners.get(event, []).remove(callback)

    def emit(self, event: str, *args) -> None:
        for cb in list(self._listeners.get(event, [])):
            cb(*args)


class _FakeCtx:
    def __init__(
        self,
        room: _FakeRoom,
        participant: _FakeParticipant | None,
        join_delay: float = 0,
    ):
        self.room = room
        self._participant = participant
        self._join_delay = join_delay

    async def wait_for_participant(self, *, kind=None):
        if self._participant is None:
            await asyncio.Event().wait()  # never joins — caller's timeout must fire
        if self._join_delay:
            await asyncio.sleep(self._join_delay)
        return self._participant


async def test_already_active_on_join_returns_immediately():
    room = _FakeRoom()
    participant = _FakeParticipant("sid-1", {_SIP_ATTR_CALL_STATUS: "active"})
    ctx = _FakeCtx(room, participant)

    assert await _wait_until_answered(ctx, timeout=1.0) is True


async def test_becomes_active_via_attribute_change_returns_true():
    room = _FakeRoom()
    participant = _FakeParticipant("sid-1", {_SIP_ATTR_CALL_STATUS: "ringing"})
    ctx = _FakeCtx(room, participant)

    async def _answer_after_delay():
        await asyncio.sleep(0.02)
        room.emit(
            "participant_attributes_changed", {_SIP_ATTR_CALL_STATUS: "active"}, participant
        )

    asyncio.create_task(_answer_after_delay())
    assert await _wait_until_answered(ctx, timeout=1.0) is True


async def test_attribute_change_for_different_participant_is_ignored():
    room = _FakeRoom()
    participant = _FakeParticipant("sid-1", {_SIP_ATTR_CALL_STATUS: "ringing"})
    other = _FakeParticipant("sid-2", {_SIP_ATTR_CALL_STATUS: "active"})
    ctx = _FakeCtx(room, participant)

    async def _emit_for_wrong_participant():
        await asyncio.sleep(0.01)
        room.emit("participant_attributes_changed", {_SIP_ATTR_CALL_STATUS: "active"}, other)

    asyncio.create_task(_emit_for_wrong_participant())
    assert await _wait_until_answered(ctx, timeout=0.1) is False


async def test_never_joins_times_out_false():
    room = _FakeRoom()
    ctx = _FakeCtx(room, participant=None)
    assert await _wait_until_answered(ctx, timeout=0.05) is False


async def test_joins_but_never_answers_times_out_false():
    room = _FakeRoom()
    participant = _FakeParticipant("sid-1", {_SIP_ATTR_CALL_STATUS: "ringing"})
    ctx = _FakeCtx(room, participant)
    assert await _wait_until_answered(ctx, timeout=0.05) is False


async def test_listener_is_removed_after_returning():
    room = _FakeRoom()
    participant = _FakeParticipant("sid-1", {_SIP_ATTR_CALL_STATUS: "ringing"})
    ctx = _FakeCtx(room, participant)

    assert await _wait_until_answered(ctx, timeout=0.05) is False
    assert room._listeners.get("participant_attributes_changed", []) == []
