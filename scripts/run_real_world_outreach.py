from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import AgentPhoneClient, AgentmailClient
from app.db import (
    connect,
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
        "call_window": "unknown",
    },
    {
        "name": "Liberated Spaces",
        "phone": "+14159026327",
        "email": "info@liberatedspaces.com",
        "website": "https://liberatedspaces.com/contact/",
        "source_note": "Official contact page lists complimentary phone assessment, phone, and email.",
        "call_window": "closed_now_google; opens 9am Monday",
    },
    {
        "name": "NEATNIK",
        "phone": None,
        "email": "info@neatnik.co",
        "website": "https://www.neatnik.co/",
        "source_note": "Official site lists Bay Area home/office organizing and public email.",
        "call_window": "email_only",
    },
    {
        "name": "Bay Area Home Organizing",
        "phone": "+18587508059",
        "email": "bahomeorganizing@gmail.com",
        "website": "https://www.bayareahomeorganizing.com/contact",
        "source_note": "Official contact page lists SF Bay service area, 9am-9pm hours, email, and phone.",
        "call_window": "daily_9_21",
    },
    {
        "name": "Clean Lines Home Organizing",
        "phone": "+14159856288",
        "email": "info@cleanlinesmarin.com",
        "website": "https://www.cleanlinesmarin.com/contact",
        "source_note": "Official contact page lists Bay Area service, email, and phone.",
        "call_window": "unknown",
    },
    {
        "name": "Cleverly Curated",
        "phone": "+14157550094",
        "email": "hello@thecleverlycurated.com",
        "website": "https://www.thecleverlycurated.com/contact",
        "source_note": "Official contact page lists San Francisco and Marin service, email, and phone/text.",
        "call_window": "unknown",
    },
    {
        "name": "Clean Cozy Home",
        "phone": "+14153401458",
        "email": "info@cleancozyhome.com",
        "website": "https://www.cleancozyhome.com/",
        "source_note": "Official site lists SF Bay Area home/office cleaning, email, and phone.",
        "call_window": "unknown",
    },
    {
        "name": "Zenfully Organized",
        "phone": "+18183060023",
        "email": "info@zenfullyorganized.com",
        "website": "https://www.zenfullyorganized.com/contact-us",
        "source_note": "Official contact page lists Bay Area organizing services, email, and phone.",
        "call_window": "unknown",
    },
    {
        "name": "Maby's Domestic Services",
        "phone": "+16509187729",
        "email": None,
        "website": "https://mabysdomesticservice.com/",
        "source_note": "Official site lists SF apartment cleaning, 15+ years experience, and phone.",
        "call_window": "unknown",
    },
    {
        "name": "ARXA Studio",
        "phone": "+18602359828",
        "email": "hotmessmethod@gmail.com",
        "website": "https://www.arxastudio.com/contact",
        "source_note": "Official contact page lists SF Bay Area service, email, and phone.",
        "call_window": "unknown",
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
        existing = provider_row(provider["name"])
        if existing and existing.get("email_status") == "sent":
            trace("sf.provider.email_skipped", f"Skipping already-sent email to {provider['name']}", task_id=SF_TASK_ID, sponsor="Agentmail")
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
        existing = provider_row(provider["name"])
        if existing and existing.get("call_id"):
            trace("sf.provider.call_skipped", f"Skipping already-called provider {provider['name']}", task_id=SF_TASK_ID, sponsor="AgentPhone", payload={"call_id": existing.get("call_id"), "call_status": existing.get("call_status")})
            continue
        if not is_open_for_call(provider):
            update_provider_attempt(provider_id, call_status="queued_until_open_hours")
            trace("sf.provider.call_deferred", f"Deferred call to {provider['name']} until open hours", task_id=SF_TASK_ID, sponsor="AgentPhone", payload={"provider": provider["name"], "call_window": provider.get("call_window")})
            continue
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
    print("NO_UNCALLED_PHONE_PROVIDERS")


def provider_row(name: str) -> dict[str, str] | None:
    with connect() as conn:
        row = conn.execute(
            "select * from provider_attempts where domain = 'sf_chores' and provider_name = ? order by id desc limit 1",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def is_open_for_call(provider: dict[str, str | None]) -> bool:
    window = provider.get("call_window") or "unknown"
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    current = now.time()
    if window == "daily_9_21":
        return time(9, 0) <= current <= time(21, 0)
    if window == "weekday_9_17":
        return now.weekday() < 5 and time(9, 0) <= current <= time(17, 0)
    if window == "email_only":
        return False
    if window.startswith("closed_now"):
        return False
    # Conservative default: do not cold-call unknown-hours providers outside business days.
    return now.weekday() < 5 and time(9, 0) <= current <= time(17, 0)


async def main() -> None:
    init_db()
    await send_sf_emails()
    await call_next_sf_provider()


if __name__ == "__main__":
    asyncio.run(main())
