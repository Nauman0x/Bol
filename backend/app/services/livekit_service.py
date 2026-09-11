import uuid

from livekit import api

from app.config import settings


def room_name_for_call(call_id: uuid.UUID) -> str:
    return f"bol-call-{call_id}"


def create_browser_access_token(room_name: str, identity: str) -> str:
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
    )
    return token.to_jwt()


def create_agent_dispatch_token(room_name: str, agent_id: uuid.UUID, call_id: uuid.UUID) -> str:
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"agent-dispatch-{call_id}")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name="bol-agent",
                        metadata=f'{{"call_id": "{call_id}", "agent_id": "{agent_id}"}}',
                    )
                ]
            )
        )
    )
    return token.to_jwt()
