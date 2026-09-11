"""Seed a demo org, user, and agent for local development.

Run with: python -m scripts.seed
"""
import asyncio
import secrets

from sqlalchemy import select

from app.db import async_session_maker
from app.models.agent import DEFAULT_AGENT_CONFIG, Agent
from app.models.organization import Organization
from app.models.user import User
from app.security import hash_password

DEMO_EMAIL = "demo@bol.dev"


async def seed() -> None:
    async with async_session_maker() as db:
        existing = await db.execute(select(User).where(User.email == DEMO_EMAIL))
        if existing.scalar_one_or_none() is not None:
            print(f"Demo user {DEMO_EMAIL} already exists, skipping seed.")
            return

        org = Organization(name="Demo Org")
        db.add(org)
        await db.flush()

        password = secrets.token_urlsafe(12)
        user = User(
            org_id=org.id,
            email=DEMO_EMAIL,
            password_hash=hash_password(password),
            name="Demo User",
            role="owner",
        )
        db.add(user)
        await db.flush()

        agent = Agent(
            org_id=org.id,
            name="Demo Support Agent",
            config={
                **DEFAULT_AGENT_CONFIG,
                "system_prompt": "You are a friendly demo support agent for Bol. Keep answers short.",
                "greeting": "Hi, thanks for calling the Bol demo. How can I help?",
            },
        )
        db.add(agent)

        await db.commit()

        print("Seeded demo data:")
        print(f"  org:      {org.name} ({org.id})")
        print(f"  email:    {DEMO_EMAIL}")
        print(f"  password: {password}")
        print(f"  agent:    {agent.name} ({agent.id})")


if __name__ == "__main__":
    asyncio.run(seed())
