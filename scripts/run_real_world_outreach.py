from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import AgentPhoneClient, AgentmailClient
from app.db import (
    create_task,
    get_task,
    init_db,
    trace,
    update_provider_attempt,
    update_task,
    upsert_provider_attempt,
)
from app.services import build_digest, parse_call_request


SF_TASK_ID = 3

SF_PROVIDERS = [
    {
        "name": "Artful Organizing SF",
        "phone": "+14152657581",
        "email": "ArtfulOrganizingSf@gmail.com",
        "website": "https://www.artfulorganizingsf.com/services",
        "source_note": "Official site lists San Francisco organizing services, email, and phone.",
    },
    {
        "name": "Liberated Spaces",
        "phone": "+14159026327",
        "email": "info@liberatedspaces.com",
        "website": "https://liberatedspaces.com/contact/",
        "source_note": "Official contact page lists complimentary phone assessment, phone, and email.",
    },
    {
        "name": "NEATNIK",
        "phone": None,
        "email": "info@neatnik.co",
        "website": "https://www.neatnik.co/",
        "source_note": "Official site lists Bay Area home/office organizing and public email.",
    },
]


def sf_email_text(provider_name: str) -> str:
    return f"""Hi {provider_name} team,

I'm looking for help in a 1BR apartment in 94109. The scope is kitchen and closet organizing, light declutter, some cleaning support, and possibly healthy meal plan / grocery support.

Weekdays after 3pm are best. For the first session, I am trying to keep it to $50-80/hour and $300 max. Could you let me know whether this is a fit, any availability this week or next, and the best next step?

Please do not book anything yet; I am just checking fit and availability.

Thank you,
Maggie
"""


def call_task_text(provider: dict[str, str | None]) -> str:
    return (
        f"Call {provider['name']} at {provider['phone']} about a 1BR apartment in 94109. "
        "Ask whether they can help with kitchen and closet organizing, light declutter, cleaning support, "
        "and possibly healthy meal plan/grocery support. Weekdays after 3pm are best. "
        "Budget is $50-80/hour and $300 max for the first session. Do not book, pay, or commit."
    )


async def send_sf_emails() -> None:
    client = AgentmailClient()
    inbox = await client.ensure_inbox()
    if not inbox:
        raise RuntimeError("Could not create Agentmail inbox")
    inbox_id = inbox.get("email") or inbox.get("inbox_id")
    if not inbox_id:
        raise RuntimeError(f"Agentmail inbox response missing email/inbox_id: {inbox}")

    for provider in SF_PROVIDERS:
        provider_id = upsert_provider_attempt(
            task_id=SF_TASK_ID,
            domain="sf_chores",
            provider_name=provider["name"],
            phone=provider["phone"],
            email=provider["email"],
            website=provider["website"],
            source_note=provider["source_note"],
        )
        if not provider["email"]:
            continue
        result = await client.send_message(
            inbox_id=inbox_id,
            to=provider["email"],
            subject="Home organizing availability inquiry for 1BR in 94109",
            text=sf_email_text(provider["name"]),
            labels=["sf-chores", "outreach"],
        )
        update_provider_attempt(
            provider_id,
            email_status="sent" if result else "failed",
            outcome=f"email sent: {json.dumps(result, default=str)[:500]}" if result else "email failed",
        )
        trace("sf.provider.email_sent", f"Sent SF inquiry email to {provider['name']}", task_id=SF_TASK_ID, sponsor="Agentmail", payload={"provider": provider["name"], "email": provider["email"], "result": result})


async def call_next_sf_provider() -> None:
    client = AgentPhoneClient()
    for provider in SF_PROVIDERS:
        if not provider["phone"]:
            continue
        provider_id = upsert_provider_attempt(
            task_id=SF_TASK_ID,
            domain="sf_chores",
            provider_name=provider["name"],
            phone=provider["phone"],
            email=provider["email"],
            website=provider["website"],
            source_note=provider["source_note"],
        )
        task_text = call_task_text(provider)
        parsed = parse_call_request(task_text)
        parsed["recipient_name"] = provider["name"]
        task_id = create_task("provider_retry", task_text, "Maggie", parsed)
        update_task(
            task_id,
            research=f"{provider['source_note']}\nWebsite: {provider['website']}",
            digest=build_digest(get_task(task_id) or {"request_text": task_text, **parsed}),
            status="ready_to_call",
        )
        result = await client.start_call(provider["phone"], get_task(task_id) or {"request_text": task_text, **parsed})
        call_id = result.get("id") or result.get("callId")
        update_task(task_id, status="calling", call_id=call_id, call_status=result.get("status") or "started")
        update_provider_attempt(provider_id, call_task_id=task_id, call_id=call_id, call_status=result.get("status") or "started")
        trace("sf.provider.call_started", f"Started SF provider retry call to {provider['name']}", task_id=task_id, sponsor="AgentPhone", payload={"provider": provider["name"], "phone": provider["phone"], "call_id": call_id})
        print(f"CALLED {provider['name']} {provider['phone']} task={task_id} call={call_id}")
        return


async def main() -> None:
    init_db()
    await send_sf_emails()
    await call_next_sf_provider()


if __name__ == "__main__":
    asyncio.run(main())
