"""Unit tests for the barge-in ack / resume-connector logic — pure state
(BargeInTracker) plus BOLAgent's on_user_turn_completed override, both
testable without a real LiveKit AgentSession/JobContext.
"""

from dataclasses import dataclass, field

import pytest

from worker.agent import BOLAgent
from worker.interruption import BargeInTracker


@dataclass(eq=False)
class _FakeHandle:
    allow_interruptions: bool = True


def test_arm_sets_latch_when_agent_speaking_and_interruptible():
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() == "Go ahead."


def test_arm_noop_when_disabled():
    tracker = BargeInTracker(enabled=False, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() is None


def test_arm_noop_when_agent_not_speaking():
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=False, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() is None


def test_arm_noop_when_no_current_handle():
    tracker = BargeInTracker(enabled=True, language="en")
    tracker.arm(agent_speaking=True, current_handle=None, excluded_handles=frozenset())
    assert tracker.take_ack() is None


def test_arm_noop_when_current_speech_not_interruptible():
    # Covers GOODBYE_TEXT / interruption_enabled=False — the framework never
    # even reaches on_user_turn_completed for uninterruptible speech, but the
    # tracker itself must also refuse to arm against it defensively.
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=False)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() is None


def test_arm_noop_when_handle_is_excluded():
    # Covers the greeting and tool-filler handles.
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset({handle}))
    assert tracker.take_ack() is None


def test_take_ack_is_single_shot():
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() == "Go ahead."
    assert tracker.take_ack() is None


def test_disarm_clears_the_latch():
    tracker = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    tracker.disarm()
    assert tracker.take_ack() is None


def test_unlisted_language_never_acks():
    tracker = BargeInTracker(enabled=True, language="th")  # not in ACK_PHRASES
    handle = _FakeHandle(allow_interruptions=True)
    tracker.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    assert tracker.take_ack() is None


# --- BOLAgent.on_user_turn_completed ---


class _FakeSpeechHandle:
    pass


@dataclass
class _FakeSession:
    said: list = field(default_factory=list)

    def say(self, text, **kwargs):
        self.said.append((text, kwargs))
        return _FakeSpeechHandle()


def _agent_with_fake_session(monkeypatch, barge_in, on_ack):
    agent = BOLAgent(barge_in=barge_in, on_ack=on_ack, instructions="be helpful")
    fake_session = _FakeSession()
    monkeypatch.setattr(BOLAgent, "session", property(lambda self: fake_session))
    return agent, fake_session


async def test_on_user_turn_completed_says_ack_exactly_once_when_armed(monkeypatch):
    barge_in = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    barge_in.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())
    acked = []
    agent, fake_session = _agent_with_fake_session(monkeypatch, barge_in, lambda: acked.append(1))

    await agent.on_user_turn_completed(None, None)

    assert len(fake_session.said) == 1
    text, kwargs = fake_session.said[0]
    assert text == "Go ahead."
    assert kwargs["allow_interruptions"] is True
    assert kwargs["add_to_chat_ctx"] is False
    assert acked == [1]


async def test_on_user_turn_completed_says_nothing_when_not_armed(monkeypatch):
    barge_in = BargeInTracker(enabled=True, language="en")
    acked = []
    agent, fake_session = _agent_with_fake_session(monkeypatch, barge_in, lambda: acked.append(1))

    await agent.on_user_turn_completed(None, None)

    assert fake_session.said == []
    assert acked == []


async def test_on_user_turn_completed_swallows_exceptions(monkeypatch):
    # An exception here must never propagate — it would make the framework
    # drop the reply for the whole turn (see agent_activity.py's caller).
    barge_in = BargeInTracker(enabled=True, language="en")
    handle = _FakeHandle(allow_interruptions=True)
    barge_in.arm(agent_speaking=True, current_handle=handle, excluded_handles=frozenset())

    def _boom():
        raise RuntimeError("boom")

    agent, _ = _agent_with_fake_session(monkeypatch, barge_in, _boom)

    await agent.on_user_turn_completed(None, None)  # must not raise
