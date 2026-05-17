from __future__ import annotations

import asyncio
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import AgentPhoneClient, AgentmailClient
from app.db import create_task, get_task, init_db, trace, update_task, upsert_provider_attempt
from app.services import build_digest, parse_call_request


TARGETS = [
    {
        "name": "Sweet Rain",
        "kind": "jazz",
        "phone": None,
        "email": "jazzsweetrain@cap.ocn.ne.jp",
        "website": "https://www.tokyogigguide.com/ja/gigs/venue/1133",
        "source_note": "Nakano live jazz dining bar; Tokyo Gig Guide lists reservation recommendation and email.",
        "call_window": "evening_unknown",
    },
    {
        "name": "Shige Tei",
        "kind": "restaurant",
        "phone": "+818070530077",
        "email": "shigetei1220@gmail.com",
        "website": "https://www.shigetei.com/english",
        "source_note": "Kagurazaka counter restaurant; official English page lists email, phone, 18:00-23:00, open daily, 18,000 yen omakase.",
        "call_window": "daily_18_23",
    },
    {
        "name": "Sushi Shutatsu",
        "kind": "restaurant",
        "phone": "+81362769113",
        "email": "shuhei.isoda@sushishutatsu.com",
        "website": "https://sushishutatsu.com/en/contactus/",
        "source_note": "Ogikubo sushi bar; official contact page lists email, phone, lunch 12-14, dinner 17-22, closed Monday.",
        "call_window": "closed_monday_lunch_dinner",
    },
    {
        "name": "HIGUCHI Head Spa",
        "kind": "spa",
        "phone": "+81355792768",
        "email": None,
        "website": "https://higuchi-totalbeauty.com/contact-en.html",
        "source_note": "Kagurazaka head spa; official page lists contact form, phone, weekdays 14:00-22:00, weekends 10:00-19:00, closed Wednesday.",
        "call_window": "tokyo_weekday_14_22_weekend_10_19_closed_wed",
    },
    {
        "name": "Ke'International Head Spa",
        "kind": "spa",
        "phone": "+81355792474",
        "email": "contact@ke-salon.com",
        "website": "https://www.ke-salon.com/head-spa/",
        "source_note": "Kagurazaka head spa page lists phone and email.",
        "call_window": "unknown",
    },
    {
        "name": "Bulgari Hotel Tokyo Spa",
        "kind": "spa",
        "phone": None,
        "email": "tyobt.spa@bulgarihotels.com",
        "website": "https://www.bulgarihotels.com/en_US/tokyo/spa-and-fitness/the-bulgari-spa",
        "source_note": "Hotel spa email already contacted; premium recharge option.",
        "call_window": "email_only",
    },
    {
        "name": "The Tokyo EDITION Spa",
        "kind": "spa",
        "phone": "+81354221640",
        "email": "SPA.TOKYO@EDITIONHOTELS.COM",
        "website": "https://thespa.toranomonedition.com/en/resourcefiles/pdf/menuen.pdf",
        "source_note": "Treatment menu PDF lists phone and spa email.",
        "call_window": "unknown",
    },
]


def email_text(target: dict[str, str | None]) -> str:
    if target["kind"] == "restaurant":
        return f"""Hello {target['name']} team,

I'm planning a 48-hour Tokyo itinerary for two guests and am checking availability for either late June or early September. We are flexible on exact dates.

We are interested in a local, memorable dinner experience, ideally not touristy. There are no allergies or dietary restrictions.

Could you let me know whether you expect to have availability for two guests, the best way to reserve, approximate pricing, and whether a deposit/card is required?

Please do not make a confirmed reservation yet; I am checking fit and availability first.

Thank you,
Maggie
"""
    if target["kind"] == "spa":
        return f"""Hello {target['name']} team,

I'm planning a 48-hour Tokyo itinerary for two guests and am looking for a relaxing spa/head-spa/massage appointment in either late June or early September.

Could you let me know whether two guests could reserve an afternoon treatment, approximate pricing, and whether non-hotel guests may book if relevant?

Please do not make a confirmed reservation yet; I am checking fit and availability first.

Thank you,
Maggie
"""
    return f"""Hello {target['name']} team,

I'm planning a 48-hour Tokyo itinerary for two guests and would love to include a warm local jazz evening in either late June or early September.

Could you let me know whether you expect to take reservations for two guests, any music charge or schedule page to watch, and the best reservation method?

Please do not make a confirmed reservation yet; I am checking fit and availability first.

Thank you,
Maggie
"""


def call_text(target: dict[str, str | None]) -> str:
    return (
        f"Call {target['name']} at {target['phone']} for Maggie's 48-hour Tokyo itinerary. "
        "Ask about availability for two guests in late June or early September, approximate price, and reservation method. "
        "Do not confirm a reservation, provide card details, pay a deposit, or make a fixed commitment."
    )


async def send_emails() -> None:
    client = AgentmailClient()
    inbox = await client.ensure_inbox()
    if not inbox:
        raise RuntimeError("Could not create Agentmail inbox")
    inbox_id = inbox.get("email") or inbox.get("inbox_id")
    if not inbox_id:
        raise RuntimeError(f"Agentmail inbox missing email/inbox_id: {inbox}")
    for target in TARGETS:
        provider_id = upsert_provider_attempt(
            domain="japan_48h",
            provider_name=target["name"],
            phone=target["phone"],
            email=target["email"],
            website=target["website"],
            source_note=target["source_note"],
        )
        if not target["email"]:
            continue
        result = await client.send_message(
            inbox_id=inbox_id,
            to=target["email"],
            subject="Availability inquiry for two guests in late June or early September",
            text=email_text(target),
            labels=["japan-48h", "outreach"],
        )
        trace("japan.email_sent", f"Sent Japan inquiry email to {target['name']}", sponsor="Agentmail", payload={"target": target["name"], "email": target["email"], "result": result})
        upsert_provider_attempt(
            domain="japan_48h",
            provider_name=target["name"],
            email_status="sent" if result else "failed",
            outcome=f"email sent: {result}" if result else "email failed",
        )


async def call_open_targets() -> None:
    client = AgentPhoneClient()
    for target in TARGETS:
        if not target["phone"]:
            continue
        provider_id = upsert_provider_attempt(
            domain="japan_48h",
            provider_name=target["name"],
            phone=target["phone"],
            email=target["email"],
            website=target["website"],
            source_note=target["source_note"],
        )
        if not is_open_for_tokyo_call(target):
            trace("japan.call_deferred", f"Deferred Japan call to {target['name']} until open hours", sponsor="AgentPhone", payload={"target": target["name"], "window": target["call_window"]})
            upsert_provider_attempt(domain="japan_48h", provider_name=target["name"], call_status="queued_until_open_hours")
            continue
        parsed = parse_call_request(call_text(target))
        parsed["recipient_name"] = target["name"]
        task_id = create_task("japan_provider_call", call_text(target), "Maggie", parsed)
        update_task(task_id, status="ready_to_call", research=target["source_note"], digest=build_digest(get_task(task_id) or {"request_text": call_text(target), **parsed}))
        result = await client.start_call(target["phone"], get_task(task_id) or {"request_text": call_text(target), **parsed})
        call_id = result.get("id") or result.get("callId")
        update_task(task_id, status="calling", call_id=call_id, call_status=result.get("status") or "started")
        upsert_provider_attempt(domain="japan_48h", provider_name=target["name"], call_task_id=task_id, call_id=call_id, call_status=result.get("status") or "started")
        trace("japan.call_started", f"Started Japan provider call to {target['name']}", task_id=task_id, sponsor="AgentPhone", payload={"target": target["name"], "phone": target["phone"], "call_id": call_id})
        print(f"CALLED {target['name']} {target['phone']} task={task_id} call={call_id}")
        return
    print("NO_OPEN_JAPAN_PHONE_TARGETS")


def is_open_for_tokyo_call(target: dict[str, str | None]) -> bool:
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    current = now.time()
    window = target["call_window"]
    if window == "daily_18_23":
        return time(18, 0) <= current <= time(23, 0)
    if window == "closed_monday_lunch_dinner":
        if now.weekday() == 0:
            return False
        return time(12, 0) <= current <= time(14, 0) or time(17, 0) <= current <= time(22, 0)
    if window == "tokyo_weekday_14_22_weekend_10_19_closed_wed":
        if now.weekday() == 2:
            return False
        if now.weekday() < 5:
            return time(14, 0) <= current <= time(22, 0)
        return time(10, 0) <= current <= time(19, 0)
    if window == "email_only":
        return False
    if window == "evening_unknown":
        return time(17, 0) <= current <= time(22, 0)
    return now.weekday() < 5 and time(10, 0) <= current <= time(18, 0)


async def main() -> None:
    init_db()
    await send_emails()
    await call_open_targets()


if __name__ == "__main__":
    asyncio.run(main())
