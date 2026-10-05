"""Thin wrapper around livekit-api for room creation + explicit agent dispatch
and outbound SIP dialing. See docs/PLAN.md Phase 4 and docs/TELEPHONY_SETUP.md.
"""

import json
import uuid
from typing import Literal

from livekit import api

from app.config import settings

AGENT_NAME = "BOL-agent"


class LiveKitNotConfiguredError(RuntimeError):
    """Raised only for missing-config cases (empty LIVEKIT_URL/keys) — a
    distinct type so callers can tell "not set up yet" apart from any other
    RuntimeError a LiveKit call might raise, and respond 503 instead of 502."""


class LiveKitService:
    def __init__(self) -> None:
        # Deliberately lazy: constructing api.LiveKitAPI eagerly would raise
        # (e.g. "url must be set" when LIVEKIT_URL isn't configured yet) before
        # a request handler's own try/except around a call ever gets to run,
        # turning a routine "LiveKit isn't set up" case into a raw 500 instead
        # of the clean 502 callers expect from create_call_room/dial_outbound.
        self._client: api.LiveKitAPI | None = None

    def _get_client(self) -> api.LiveKitAPI:
        if self._client is None:
            if not settings.livekit_url:
                raise LiveKitNotConfiguredError("LIVEKIT_URL is not configured")
            self._client = api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
        return self._client

    async def create_call_room(
        self,
        room_name: str,
        call_id: uuid.UUID | None,
        agent_id: uuid.UUID,
        transport: Literal["telephony", "webrtc"],
    ) -> None:
        """Create a room with the BOL agent explicitly dispatched into it,
        carrying {call_id, agent_id, transport} as job metadata (see
        worker/agent.py). call_id is None for browser test sessions, which
        have no Call row — the worker's EventReporter no-ops (logs only)
        when call_id is absent. transport tells the worker whether to wait
        for SIP answer confirmation before greeting (telephony) or not
        (webrtc) — decided here by the caller (outbound call vs test
        session), not guessed by the worker."""
        metadata = json.dumps(
            {
                "call_id": str(call_id) if call_id else None,
                "agent_id": str(agent_id),
                "transport": transport,
            }
        )
        await self._get_client().room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)],
            )
        )

    async def dial_outbound(
        self, room_name: str, to_number: str, from_trunk_id: str | None, from_number: str | None
    ) -> api.SIPParticipantInfo:
        """from_trunk_id/from_number come from the dialing PhoneNumber row
        (its own carrier's trunk + caller ID), falling back to the
        platform-wide LIVEKIT_SIP_OUTBOUND_TRUNK_ID default when the number
        has no trunk of its own — this is what lets different phone numbers
        route through different carriers (e.g. Telnyx and Twilio side by
        side) instead of every outbound call using one hardcoded trunk."""
        trunk_id = from_trunk_id or settings.livekit_sip_outbound_trunk_id
        if not trunk_id:
            raise LiveKitNotConfiguredError(
                "No SIP trunk configured for this number and "
                "LIVEKIT_SIP_OUTBOUND_TRUNK_ID is not set"
            )
        return await self._get_client().sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=to_number,
                sip_number=from_number or "",
                room_name=room_name,
                participant_identity=f"sip-{to_number}",
                wait_until_answered=False,
            )
        )

    async def delete_room(self, room_name: str) -> None:
        await self._get_client().room.delete_room(api.DeleteRoomRequest(room=room_name))

    def generate_join_token(self, room_name: str, identity: str, name: str) -> str:
        """A browser-joinable token for the agent-builder's in-app test-call
        panel — publish+subscribe only, scoped to a single room."""
        if not settings.livekit_api_key or not settings.livekit_api_secret:
            raise LiveKitNotConfiguredError("LIVEKIT_API_KEY/LIVEKIT_API_SECRET are not configured")
        grants = api.VideoGrants(
            room_join=True, room=room_name, can_publish=True, can_subscribe=True
        )
        return (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(grants)
            .to_jwt()
        )

    def generate_listen_token(self, room_name: str, identity: str, name: str) -> str:
        """Subscribe-only — for the dashboard's "listen in" on a live call.
        can_publish=False so a monitoring browser tab can never be picked up
        as an audio source in the room; hidden=True keeps it out of the
        agent's/caller's participant list."""
        if not settings.livekit_api_key or not settings.livekit_api_secret:
            raise LiveKitNotConfiguredError("LIVEKIT_API_KEY/LIVEKIT_API_SECRET are not configured")
        grants = api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=False,
            can_subscribe=True,
            hidden=True,
        )
        return (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(grants)
            .to_jwt()
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def get_livekit_service() -> LiveKitService:
    return LiveKitService()
