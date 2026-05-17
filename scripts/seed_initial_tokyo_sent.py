from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db, trace, upsert_provider_attempt
from scripts.send_tokyo_outreach import TARGETS


def main() -> None:
    init_db()
    for target in TARGETS:
        upsert_provider_attempt(
            domain="japan_48h",
            provider_name=target["name"],
            email=target["email"],
            email_status="sent",
            outcome="email sent before provider_attempts table existed; see Agentmail send events and script body",
        )
        trace("japan.initial_sent_seeded", f"Seeded sent status for {target['name']}", sponsor="Agentmail", payload={"target": target["name"], "email": target["email"]})
        print(f"seeded {target['name']} {target['email']}")


if __name__ == "__main__":
    main()
