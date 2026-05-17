from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
SECRETS_DIR = Path.home() / "Documents" / "secrets"


def load_secret_env() -> None:
    for name in (
        ".env.github",
        ".env.browser-use",
        ".env.supermemory",
        ".env.agentmail",
        ".env.agentphone",
    ):
        load_dotenv(SECRETS_DIR / name, override=False)
    load_dotenv(ROOT / ".env", override=False)


class Settings(BaseModel):
    agentphone_api_key: str | None = None
    agentphone_agent_id: str | None = None
    agentphone_phone_number_id: str | None = None
    agentphone_phone_number: str | None = None
    browser_use_api_key: str | None = None
    supermemory_api_key: str | None = None
    agentmail_api_key: str | None = None
    github_token: str | None = None
    ngrok_url: str | None = None
    public_base_url: str | None = None
    allow_live_calls: bool = False
    demo_user_name: str = "Maggie"
    database_path: Path = DATA_DIR / "call_delegator.sqlite3"
    trace_path: Path = LOG_DIR / "trace.jsonl"

    @classmethod
    def from_env(cls) -> "Settings":
        load_secret_env()
        return cls(
            agentphone_api_key=os.getenv("AGENTPHONE_API_KEY"),
            agentphone_agent_id=os.getenv("AGENTPHONE_AGENT_ID"),
            agentphone_phone_number_id=os.getenv("AGENTPHONE_PHONE_NUMBER_ID"),
            agentphone_phone_number=os.getenv("AGENTPHONE_PHONE_NUMBER"),
            browser_use_api_key=os.getenv("BROWSER_USE_API_KEY"),
            supermemory_api_key=os.getenv("SUPERMEMORY_API_KEY"),
            agentmail_api_key=os.getenv("AGENTMAIL_API_KEY"),
            github_token=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"),
            ngrok_url=os.getenv("NGROK_URL"),
            public_base_url=os.getenv("PUBLIC_BASE_URL") or os.getenv("NGROK_URL"),
            allow_live_calls=os.getenv("ALLOW_LIVE_CALLS", "").lower() in {"1", "true", "yes"},
            demo_user_name=os.getenv("DEMO_USER_NAME", "Maggie"),
        )

    def env_status(self) -> dict[str, bool]:
        return {
            "AgentPhone": bool(self.agentphone_api_key and self.agentphone_agent_id),
            "Browser Use": bool(self.browser_use_api_key),
            "Supermemory": bool(self.supermemory_api_key),
            "Agentmail": bool(self.agentmail_api_key),
            "GitHub": bool(self.github_token),
            "ngrok/Railway URL": bool(self.public_base_url),
            "Live PSTN calls enabled": self.allow_live_calls,
        }


settings = Settings.from_env()
