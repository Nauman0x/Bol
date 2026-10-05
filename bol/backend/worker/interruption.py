"""Barge-in acknowledgment and false-interruption resume-connector logic.

Pure, livekit-free state (BargeInTracker) plus the phrase tables, so the
arm/disarm/consume logic is unit-testable without constructing a real
AgentSession — see backend/tests/test_worker.py.

worker/agent.py wires this to session events:
  - user_state_changed -> speaking            -> BargeInTracker.arm(...)
  - agent_false_interruption                  -> BargeInTracker.disarm()
  - agent_state_changed -> speaking            -> BargeInTracker.disarm()
  - Agent.on_user_turn_completed override      -> BargeInTracker.take_ack()

See docs/PLAN.md / the interruption-handling plan for why the ack fires from
on_user_turn_completed (after the interrupted handle is resolved, before the
reply is scheduled) rather than at barge-in time (the caller is still
talking, and the agent's own paused audio is still "current").
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from livekit.agents.voice.speech_handle import SpeechHandle

# Only languages with a genuine translation get an entry — same rule as
# worker/agent.py's _FILLER_PHRASES: an agent whose language isn't listed
# gets no spoken ack at all rather than an English phrase blurted mid-call.
# Phrases are deliberately NOT answer-openers ("Sure," "Okay,") so they
# can't be mistaken for the start of the real reply that follows them.
ACK_PHRASES: dict[str, list[str]] = {
    "en": ["Go ahead.", "Mm-hm.", "Sure."],
    "ar": ["تفضل.", "نعم."],
    "es": ["Adelante.", "Ajá."],
    "fr": ["Je vous écoute.", "Mm-hm."],
    "de": ["Bitte.", "Mhm."],
    "hi": ["जी बोलिए।", "हाँ।"],
    "ur": ["جی فرمائیں۔", "جی۔"],
    "pt": ["Pode falar.", "Sim."],
    "ru": ["Слушаю.", "Угу."],
    "zh": ["请说。", "嗯。"],
}


@dataclass
class BargeInTracker:
    """One instance per call. Tracks whether the caller's current speech
    is a "real" interruption of the agent (armed) that should get a short
    spoken acknowledgment once the turn actually commits.
    """

    enabled: bool
    language: str

    def __post_init__(self) -> None:
        self._armed_handle: "SpeechHandle | None" = None

    def arm(
        self,
        *,
        agent_speaking: bool,
        current_handle: "SpeechHandle | None",
        excluded_handles: frozenset,
    ) -> None:
        """Call on user_state_changed -> "speaking". Only arms when the
        agent's current speech is genuinely interruptible and isn't the
        greeting or a tool filler — those already have their own handling
        and acking them would be confusing or redundant."""
        if not self.enabled or not agent_speaking or current_handle is None:
            return
        if not current_handle.allow_interruptions:
            return
        if current_handle in excluded_handles:
            return
        self._armed_handle = current_handle

    def disarm(self) -> None:
        """Call on agent_false_interruption (the interruption turned out to
        be nothing) and on agent_state_changed -> "speaking" (a new agent
        turn started, any stale arm from a prior turn is no longer valid)."""
        self._armed_handle = None

    def take_ack(self) -> str | None:
        """Call from Agent.on_user_turn_completed. Returns an ack phrase at
        most once per arm — clears the latch whether or not a phrase was
        available, so a later call in the same turn (there should be at
        most one) never double-fires."""
        if self._armed_handle is None:
            return None
        self._armed_handle = None
        phrases = ACK_PHRASES.get(self.language)
        if not phrases:
            return None
        # First phrase, not random — a random pick occasionally choosing
        # "Mm-hm." right before a long answer reads as dismissive; "Go
        # ahead." is the safest universal choice. Kept as a list (not a
        # single constant) so a future revision can rotate without an API
        # change.
        return phrases[0]
