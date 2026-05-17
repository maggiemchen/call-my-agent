from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .clients import AgentPhoneClient, AgentmailClient, SupermemoryClient, browser_research, call_system_prompt
from .config import settings
from .db import create_task, get_task, trace, update_task


PHONE_RE = re.compile(r"(\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})")


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return raw if raw.startswith("+") else None


def parse_call_request(text: str) -> dict[str, Any]:
    match = PHONE_RE.search(text)
    phone = normalize_phone(match.group(1)) if match else None
    without_phone = PHONE_RE.sub("", text).strip(" ,.-")
    recipient_name = None
    objective = without_phone
    lowered = without_phone.lower()
    if lowered.startswith("call "):
        rest = without_phone[5:].strip()
        parts = re.split(r"\b(?:and|to)\b", rest, maxsplit=1, flags=re.I)
        recipient_name = parts[0].strip(" ,.-") or None
        objective = parts[1].strip(" ,.-") if len(parts) > 1 else rest
    return {
        "recipient_name": recipient_name,
        "recipient_phone": phone,
        "objective": objective or text,
        "constraints": "Domestic MVP: no payment, booking, or account authentication without Maggie confirmation.",
    }


async def create_and_process_task(source: str, request_text: str, requester: str | None = None, *, live: bool = False) -> dict[str, Any]:
    parsed = parse_call_request(request_text)
    task_id = create_task(source, request_text, requester, parsed)
    asyncio.create_task(process_task(task_id, live=live))
    task = get_task(task_id) or {}
    return task


async def process_task(task_id: int, *, live: bool) -> None:
    task = get_task(task_id)
    if not task:
        return
    update_task(task_id, status="researching")
    trace("task.research.started", "Starting Browser Use and Supermemory research", task_id=task_id)

    memory_client = SupermemoryClient()
    memory_task = memory_client.search(task.get("recipient_name") or task["request_text"])
    research_task = browser_research(task)
    memory, research = await asyncio.gather(memory_task, research_task)

    memory_text = json.dumps(memory, default=str)[:3000] if memory else ""
    update_task(task_id, status="ready_to_call", research=research, memory=memory_text)
    trace("task.research.completed", "Research attached to task", task_id=task_id, payload={"research_chars": len(research), "has_memory": bool(memory)})

    digest = build_digest(get_task(task_id) or task)
    update_task(task_id, digest=digest)
    await memory_client.add(digest, {"project": "agentphone-call-delegator", "task_id": task_id, "kind": "call-task"})

    if live and settings.allow_live_calls and task.get("recipient_phone"):
        await start_live_call(task_id)
    else:
        reason = "live disabled"
        if live and not settings.allow_live_calls:
            reason = "ALLOW_LIVE_CALLS is not true"
        if live and not task.get("recipient_phone"):
            reason = "no recipient phone parsed"
        update_task(task_id, status="staged_call", call_status=reason)
        trace("call.staged", f"Call staged: {reason}", task_id=task_id, ok=not live)


async def start_live_call(task_id: int) -> None:
    task = get_task(task_id)
    if not task:
        return
    update_task(task_id, status="calling", call_status="starting")
    try:
        client = AgentPhoneClient()
        result = await client.start_call(task["recipient_phone"], task)
        call_id = result.get("id") or result.get("callId")
        update_task(task_id, status="calling", call_id=call_id, call_status=result.get("status") or "started")
        trace("call.started", "AgentPhone outbound call started", sponsor="AgentPhone", task_id=task_id, payload={"call_id": call_id, "status": result.get("status")})
    except Exception as exc:
        update_task(task_id, status="blocked", call_status=str(exc))
        trace("call.failed", f"AgentPhone outbound call failed: {exc}", sponsor="AgentPhone", task_id=task_id, ok=False)


def build_digest(task: dict[str, Any]) -> str:
    return f"""Life Ops Concierge call packet

Request: {task.get('request_text')}
Recipient: {task.get('recipient_name') or 'Unknown'} {task.get('recipient_phone') or ''}
Objective: {task.get('objective') or 'Unknown'}
Status: {task.get('status')}

Research:
{task.get('research') or 'Pending'}

Call rules:
- AI disclosure required.
- No payment, booking, account auth, or irreversible commitment without Maggie confirmation.
- Final output should be a concise result, transcript highlights, and next action.
"""


def voice_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    transcript = data.get("transcript") or data.get("message") or ""
    task = get_task(int(data.get("task_id"))) if str(data.get("task_id", "")).isdigit() else None
    text = transcript.lower()
    if any(word in text for word in ("voicemail", "leave a message", "after the tone")):
        return {
            "text": "Hi, this is an AI call agent calling on behalf of Maggie. I am calling about a scheduling task. Please text or call Maggie back when convenient. Thank you.",
            "hangup": True,
        }
    if re.search(r"\bpress (one|1)\b|\bfor .* press 1\b", text):
        return {"text": "I'll choose the option to speak with someone.", "digits": "1"}
    objective = (task or {}).get("objective") or "Maggie's request"
    return {
        "text": f"Thanks. I am calling on behalf of Maggie about {objective}. I can share scheduling preferences, but if payment or account verification is needed I will pause and have Maggie confirm.",
    }


async def ensure_agentmail_inbox() -> dict[str, Any] | None:
    return await AgentmailClient().ensure_inbox()


def output_concepts() -> list[dict[str, str]]:
    return [
        {"name": "Live Call Mission Control", "pro": "Judges instantly see queue, sponsor stack, transcript, and next action.", "con": "Needs local server/browser running."},
        {"name": "Call Receipt Card", "pro": "A shareable artifact per call with outcome, transcript highlights, and proof links.", "con": "Less dramatic while the call is happening."},
        {"name": "AgentPhone Web Booth", "pro": "Works even if PSTN number stays SMS-only; audience can talk to the agent in-browser.", "con": "Slightly less real-world than a phone number calling a business."},
        {"name": "Before/After Burden Meter", "pro": "Makes the emotional payoff obvious in 10 seconds.", "con": "Can feel gimmicky if overused."},
        {"name": "Vendor Research Dossier", "pro": "Shows Browser Use doing real work before the call.", "con": "Research is not the core magic moment."},
        {"name": "Memory Timeline", "pro": "Supermemory becomes visible across repeated calls.", "con": "Needs two calls to really land."},
        {"name": "Inbox Digest", "pro": "Agentmail becomes concrete with an email-ready summary.", "con": "Email is asynchronous and less stage-friendly."},
        {"name": "Phone Tree Replay", "pro": "Visually explains IVR navigation and DTMF choices.", "con": "Only useful if the call hits an IVR."},
        {"name": "Escalation Rail", "pro": "Shows safety boundaries for payment/auth/booking.", "con": "Safety UI can distract from momentum."},
        {"name": "Sponsor Flight Recorder", "pro": "Every API call is timestamped; excellent for debugging and judging proof.", "con": "Too technical as the main demo surface."},
    ]


def final_output_picks() -> list[str]:
    return ["Live Call Mission Control", "Call Receipt Card", "AgentPhone Web Booth"]
