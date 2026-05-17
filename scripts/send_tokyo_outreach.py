from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import AgentmailClient
from app.db import init_db, trace


TARGETS = [
    {
        "name": "Sweet Rain",
        "email": "jazzsweetrain@cap.ocn.ne.jp",
        "subject": "Reservation inquiry for two guests in late June or early September",
        "text": """Hello Sweet Rain team,

I'm planning a 48-hour Tokyo trip for two people and would love to include a small live jazz evening in Nakano.

Could you let me know whether you expect to take reservations for two guests on a weekday evening in either late June or early September? We are flexible on the exact date and time. If there is a preferred way to reserve, a music charge, or a schedule page we should watch, please send it over.

No allergies or dietary restrictions. We are looking for a warm, local, music-focused night rather than anything touristy.

Thank you,
Maggie
""",
    },
    {
        "name": "Bulgari Hotel Tokyo Spa",
        "email": "tyobt.spa@bulgarihotels.com",
        "subject": "Spa availability inquiry for two guests in late June or early September",
        "text": """Hello Bulgari Hotel Tokyo Spa team,

I'm planning a 48-hour Tokyo itinerary for two guests and am looking for a restorative spa or massage appointment.

Could you let me know whether you have availability for two guests in either late June or early September? We are flexible on exact dates. We are most interested in massage, head spa, or a calming recharge treatment, ideally in the afternoon.

Please also share approximate pricing and whether non-hotel guests may reserve.

Thank you,
Maggie
""",
    },
]


async def main() -> None:
    init_db()
    client = AgentmailClient()
    inbox = await client.ensure_inbox()
    if not inbox:
        raise SystemExit("Agentmail inbox could not be created")
    inbox_id = inbox.get("email") or inbox.get("inbox_id")
    if not inbox_id:
        raise SystemExit(f"Agentmail inbox response missing email/inbox_id: {inbox}")

    send = os.getenv("TOKYO_OUTREACH_SEND", "").lower() in {"1", "true", "yes"}
    for target in TARGETS:
        if not send:
            trace("tokyo.outreach.draft", f"Drafted outreach to {target['name']}", sponsor="Agentmail", payload=target)
            print(f"DRY RUN {target['name']} <{target['email']}>")
            continue
        result = await client.send_message(
            inbox_id=inbox_id,
            to=target["email"],
            subject=target["subject"],
            text=target["text"],
            labels=["tokyo-48h", "outreach", "hackathon"],
        )
        print(f"SENT {target['name']} <{target['email']}> {result}")


if __name__ == "__main__":
    asyncio.run(main())
