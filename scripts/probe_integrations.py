from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import AgentPhoneClient
from app.config import settings
from app.db import init_db, trace


async def main() -> None:
    init_db()
    print(json.dumps(settings.env_status(), indent=2))
    client = AgentPhoneClient()
    status = await client.status()
    numbers = status["numbers"].get("data", [])
    first_number = numbers[0] if numbers else {}
    voices = await client.request("GET", "/agents/voices")
    web_call = await client.web_call()
    summary = {
        "agentphone_number": {
            "id": first_number.get("id"),
            "phoneNumber": first_number.get("phoneNumber"),
            "status": first_number.get("status"),
            "type": first_number.get("type"),
            "capabilities": first_number.get("capabilities"),
        },
        "voice_count": len(voices.get("data", [])),
        "web_call_token_ok": bool(web_call.get("accessToken")),
        "web_call_id": web_call.get("id") or web_call.get("callId"),
    }
    trace("probe.completed", "Integration probe completed", payload=summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
