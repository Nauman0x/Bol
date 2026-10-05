"""Idempotent demo-data seed. Run with: python -m scripts.seed"""

import asyncio
import secrets

from sqlalchemy import select

from app.db import async_session_factory
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.security import hash_password

DEMO_ORG_NAME = "BOL Demo"
DEMO_EMAIL = "demo@BOL.dev"
DEMO_AGENT_NAME = "BOL Receptionist"

DEMO_PROMPT = (
    "You are the BOL receptionist, a multilingual AI phone agent. Greet callers "
    "warmly, answer questions about BOL's AI calling platform, and offer to "
    "transfer to a human if asked. Detect the caller's language from their first "
    "sentence and respond in that same language, whatever it is. Keep responses "
    "under 3 sentences.\n\n"
    "أنت موظف الاستقبال الافتراضي لبول، مساعد صوتي متعدد اللغات. "
    "رحّب بالمتصلين بحرارة وأجب عن أسئلتهم حول منصة الاتصال الذكي بول."
)


async def seed() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Organization).where(Organization.name == DEMO_ORG_NAME))
        org = result.scalar_one_or_none()
        if org is None:
            org = Organization(name=DEMO_ORG_NAME)
            db.add(org)
            await db.flush()
            print(f"Created organization: {org.name} ({org.id})")
        else:
            print(f"Organization already exists: {org.name} ({org.id})")

        result = await db.execute(select(User).where(User.email == DEMO_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            password = secrets.token_urlsafe(12)
            user = User(
                org_id=org.id,
                email=DEMO_EMAIL,
                password_hash=hash_password(password),
                name="Demo Owner",
                role=UserRole.owner,
            )
            db.add(user)
            print(f"Created user: {DEMO_EMAIL} / password: {password}  (SAVE THIS — shown once)")
        else:
            print(f"User already exists: {DEMO_EMAIL} (password unchanged)")

        result = await db.execute(
            select(Agent).where(Agent.org_id == org.id, Agent.name == DEMO_AGENT_NAME)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            agent = Agent(
                org_id=org.id,
                name=DEMO_AGENT_NAME,
                config={
                    "system_prompt": DEMO_PROMPT,
                    "greeting": "Hello, thank you for calling BOL. How can I help you today?",
                    "language": "auto",
                    "voice_id": "default",
                    "llm_model": "qwen/qwen3.6-27b",
                    "temperature": 0.7,
                    "max_call_duration_sec": 600,
                    "interruption_enabled": True,
                },
                tools=[],
                is_active=True,
            )
            db.add(agent)
            print(f"Created agent: {agent.name}")
        else:
            print(f"Agent already exists: {agent.name}")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
