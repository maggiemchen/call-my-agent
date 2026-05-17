from __future__ import annotations

import json
from typing import Any

import httpx

from .config import settings
from .db import trace


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if "token" in k.lower() or "key" in k.lower() or k.lower() == "authorization" else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class AgentPhoneClient:
    base_url = "https://api.agentphone.ai/v1"

    def __init__(self) -> None:
        self.api_key = settings.agentphone_api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("AGENTPHONE_API_KEY missing")
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.request(method, f"{self.base_url}{path}", headers=self.headers, json=json_body)
        try:
            body = res.json() if res.content else {}
        except json.JSONDecodeError:
            body = {"raw": res.text[:500]}
        trace("agentphone.http", f"{method} {path} -> {res.status_code}", sponsor="AgentPhone", ok=res.is_success, payload=_redact(body))
        res.raise_for_status()
        return body

    async def status(self) -> dict[str, Any]:
        agents = await self.request("GET", "/agents?limit=10")
        numbers = await self.request("GET", "/numbers?limit=20")
        webhook = await self.request("GET", "/webhooks")
        return {"agents": agents, "numbers": numbers, "webhook": webhook}

    async def register_webhook(self, public_base_url: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/webhooks",
            json_body={"url": f"{public_base_url.rstrip('/')}/webhooks/agentphone", "contextLimit": 10, "timeout": 20},
        )

    async def test_webhook(self) -> dict[str, Any]:
        return await self.request("POST", "/webhooks/test", json_body={})

    async def prepare_agent_for_webhook(self) -> dict[str, Any]:
        prompt = call_system_prompt()
        return await self.request(
            "PATCH",
            f"/agents/{settings.agentphone_agent_id}",
            json_body={
                "voiceMode": "webhook",
                "systemPrompt": prompt,
                "voicemailMessage": "Hi, this is Maggie's call agent. I am calling on her behalf and will text a concise follow-up. Thank you.",
            },
        )

    async def start_call(self, to_number: str, task: dict[str, Any]) -> dict[str, Any]:
        body = {
            "agentId": settings.agentphone_agent_id,
            "toNumber": to_number,
            "fromNumberId": settings.agentphone_phone_number_id,
            "initialGreeting": initial_greeting(task),
            "systemPrompt": call_system_prompt(task),
        }
        return await self.request("POST", "/calls", json_body={k: v for k, v in body.items() if v})

    async def web_call(self, task_id: int | None = None) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/calls/web",
            json_body={"agentId": settings.agentphone_agent_id, "metadata": {"task_id": task_id, "surface": "hackathon-dashboard"}},
        )


class SupermemoryClient:
    base_url = "https://api.supermemory.ai/v3"

    def __init__(self) -> None:
        self.api_key = settings.supermemory_api_key

    async def search(self, query: str) -> dict[str, Any] | None:
        if not self.api_key:
            trace("supermemory.skipped", "SUPERMEMORY_API_KEY missing", sponsor="Supermemory", ok=False)
            return None
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.post(
                f"{self.base_url}/search",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"q": query, "limit": 5},
            )
        body = res.json() if res.content else {}
        trace("supermemory.search", f"Search -> {res.status_code}", sponsor="Supermemory", ok=res.is_success, payload=_redact(body))
        return body if res.is_success else None

    async def add(self, content: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.post(
                f"{self.base_url}/memories",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"content": content, "metadata": metadata},
            )
        body = res.json() if res.content else {}
        trace("supermemory.add", f"Add memory -> {res.status_code}", sponsor="Supermemory", ok=res.is_success, payload=_redact(body))
        return body if res.is_success else None


class AgentmailClient:
    base_url = "https://api.agentmail.to/v0"

    def __init__(self) -> None:
        self.api_key = settings.agentmail_api_key

    async def ensure_inbox(self) -> dict[str, Any] | None:
        if not self.api_key:
            trace("agentmail.skipped", "AGENTMAIL_API_KEY missing", sponsor="Agentmail", ok=False)
            return None
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.post(
                f"{self.base_url}/inboxes",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"client_id": "agentphone-call-delegator-v1", "display_name": "Life Ops Concierge"},
            )
        body = res.json() if res.content else {}
        trace("agentmail.inbox", f"Ensure inbox -> {res.status_code}", sponsor="Agentmail", ok=res.is_success, payload=_redact(body))
        return body if res.is_success else None

    async def send_message(
        self,
        *,
        inbox_id: str,
        to: str | list[str],
        subject: str,
        text: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if not self.api_key:
            trace("agentmail.skipped", "AGENTMAIL_API_KEY missing", sponsor="Agentmail", ok=False)
            return None
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.post(
                f"{self.base_url}/inboxes/{inbox_id}/messages/send",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"to": to, "subject": subject, "text": text, "labels": labels or ["outreach"]},
            )
        body = res.json() if res.content else {}
        trace("agentmail.send", f"Send message -> {res.status_code}", sponsor="Agentmail", ok=res.is_success, payload=_redact({"to": to, "subject": subject, "body": body}))
        return body if res.is_success else None


async def browser_research(task: dict[str, Any]) -> str:
    if not settings.browser_use_api_key:
        trace("browser_use.skipped", "BROWSER_USE_API_KEY missing", sponsor="Browser Use", ok=False, task_id=task["id"])
        return "Browser Use skipped because no API key was loaded."
    prompt = browser_research_prompt(task)
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse

        client = AsyncBrowserUse(api_key=settings.browser_use_api_key)
        result = await client.run(prompt, model="claude-sonnet-4.6")
        output = getattr(result, "output", None) or str(result)
        trace("browser_use.research", "Browser Use research completed", sponsor="Browser Use", task_id=task["id"], payload={"chars": len(output)})
        return output
    except Exception as exc:
        trace("browser_use.error", f"Browser Use failed: {exc}", sponsor="Browser Use", ok=False, task_id=task["id"])
        return f"Browser Use failed: {exc}"


def browser_research_prompt(task: dict[str, Any]) -> str:
    text = task["request_text"]
    if any(term in text.lower() for term in ("taskrabbit", "thumbtack", "yelp", "home organizer", "cleaning helper", "94109", "closet")):
        return f"""Use Browser Use to do real-world vendor research for this SF life-ops task.

Task:
{text}

Requirements:
- Research TaskRabbit, Thumbtack, Yelp, Google/local web results, or public provider sites.
- Find 3-5 real candidate providers that can plausibly help with a 1BR in 94109.
- Apply this quality rule where visible: at least 10 reviews and 4.8+ stars, or 50+ reviews and 4.5+ stars.
- Budget fit: $50-80/hour, $300 max right now.
- Timing: weekdays after 3pm, not late at night.
- Scope: kitchen and closet organizing, declutter, light cleaning, healthy meal plan/grocery support.
- Do not book, pay, submit forms, send messages, or make external commitments.

Return a structured brief in this exact shape:
1. BEST_CALL_TARGET: provider name, public phone number if found, source URL, why this is the first call.
2. SHORTLIST: 3-5 providers with rating/review evidence, phone/contact path, source, estimated fit.
3. MESSAGE_DRAFTS: one natural TaskRabbit/Thumbtack/Yelp message Maggie could send.
4. CALL_SCRIPT: 45-second opening for an AI call agent calling on Maggie's behalf.
5. BLOCKERS: anything missing, account/login wall, no phone listed, uncertain reviews, or policy risk.
"""
    return (
        "Research this domestic call task for a phone-call agent. "
        "Return: likely business/person, phone validity, hours if public, call objective, "
        "gotchas, and a concise suggested opening. Do not book, message, or submit forms.\n\n"
        f"Task: {text}"
    )


def initial_greeting(task: dict[str, Any]) -> str:
    objective = task.get("objective") or "a quick scheduling question"
    return f"Hi, this is an AI call agent calling on behalf of Maggie. I am calling about {objective}. Is now a good time?"


def call_system_prompt(task: dict[str, Any] | None = None) -> str:
    task_text = task.get("request_text") if task else "the active call task"
    research = task.get("research") if task else ""
    return f"""You are Life Ops Concierge, an AI phone-call agent. You are calling on behalf of Maggie.

Rules:
- Be direct, warm, and brief. Do not claim to be human.
- If asked who you are, say: "I'm an AI call agent calling on Maggie's behalf."
- Handle domestic service calls, restaurant availability, scheduling, vendor questions, and voicemail.
- Never provide sensitive authentication, payment details, SSN, passwords, or card numbers.
- If payment, booking, account auth, medical/legal/financial advice, or irreversible commitment is required, pause and say Maggie will confirm by text.
- For IVRs, return digits when useful.
- End with a crisp summary and next action.

Current task: {task_text}
Research/memory: {research or "No external research attached yet."}
"""
