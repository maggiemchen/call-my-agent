from __future__ import annotations

import html
import json
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .clients import AgentPhoneClient, call_system_prompt
from .config import settings
from .db import (
    create_demo_run,
    find_task_by_call_id,
    get_task,
    init_db,
    latest_demo_run,
    latest_task,
    list_events,
    list_provider_attempts,
    list_tasks,
    log_webhook,
    trace,
    update_demo_run,
    update_provider_attempt_by_call_id,
    update_task,
)
from .services import (
    create_and_process_task,
    ensure_agentmail_inbox,
    final_output_picks,
    output_concepts,
    parse_call_request,
    start_live_call,
    voice_response,
)

app = FastAPI(title="Life Ops Concierge", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    trace("app.startup", "FastAPI app started", payload={"env": settings.env_status()})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "env": settings.env_status()}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/artifacts/{filename}", include_in_schema=False)
async def artifact_file(filename: str) -> FileResponse:
    return FileResponse(f"artifacts/{filename}")


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return render_dashboard()


@app.get("/showcase", response_class=HTMLResponse)
async def showcase() -> str:
    return render_showcase()


@app.post("/demo/e2e/start")
async def demo_e2e_start() -> RedirectResponse:
    create_demo_run(
        "Find someone to organize my 1BR in 94109. Kitchen and closet, weekdays after 3pm, $300 max. Also build a 48-hour Tokyo plan with jazz, unusual dinner, and spa. Don't book without asking me."
    )
    return RedirectResponse("/showcase", status_code=303)


@app.post("/demo/e2e/reply")
async def demo_e2e_reply() -> RedirectResponse:
    demo = latest_demo_run()
    if not demo:
        create_demo_run("Demo task")
        demo = latest_demo_run()
    vendor_reply = (
        "Clean Lines Home Organizing replied: Tuesday 4pm works. "
        "$75/hour, 3-hour starter session, kitchen + closet focus is a fit. "
        "They can add light declutter support; no payment needed until Maggie confirms."
    )
    packet = (
        "Approval packet: Recommend Clean Lines for Tuesday 4pm, $225 estimated total. "
        "Continue Japan outreach while waiting for Sweet Rain / Sushi Shutatsu / spa replies. "
        "Say YES to approve the Clean Lines booking request; say NO to keep searching."
    )
    update_demo_run(
        demo["id"],
        status="approval_ready",
        research_status="real providers researched",
        email_status="vendor replied in controlled inbox",
        vendor_reply=vendor_reply,
        approval_packet=packet,
    )
    trace("demo.vendor_reply", "Controlled vendor reply received", payload={"demo_id": demo["id"], "vendor_reply": vendor_reply})
    return RedirectResponse("/showcase", status_code=303)


@app.post("/demo/e2e/call")
async def demo_e2e_call() -> RedirectResponse:
    demo = latest_demo_run()
    if not demo:
        create_demo_run("Demo task")
        demo = latest_demo_run()
    update_demo_run(
        demo["id"],
        status="approval_ready",
        call_status="controlled receptionist call completed; provider can do Tuesday 4pm",
    )
    trace("demo.call_completed", "Controlled call completed with viable appointment option", payload={"demo_id": demo["id"]})
    return RedirectResponse("/showcase", status_code=303)


@app.post("/tasks")
async def create_task_endpoint(
    request_text: str = Form(...),
    requester: str | None = Form(None),
    live: bool = Form(False),
) -> RedirectResponse:
    await create_and_process_task("dashboard", request_text, requester, live=live)
    return RedirectResponse("/", status_code=303)


@app.post("/api/tasks")
async def create_task_api(request: Request) -> dict[str, Any]:
    body = await request.json()
    task = await create_and_process_task("api", body["request_text"], body.get("requester"), live=bool(body.get("live")))
    return {"ok": True, "task": task}


@app.post("/demo/domestic")
async def demo_domestic() -> RedirectResponse:
    await create_and_process_task(
        "demo",
        "Use TaskRabbit, Thumbtack, Yelp, Google, and public provider sites to find a real highly rated SF home organizer or cleaning helper for a 1BR in 94109. Need weekday availability after 3pm for kitchen and closet organizing, light declutter, cleaning, and healthy meal plan/grocery support. Budget is $50-80/hour and $300 max right now. If a public phone number is found, prepare the first call. Do not book, pay, submit forms, or send messages.",
        "Maggie",
        live=False,
    )
    return RedirectResponse("/", status_code=303)


@app.post("/tasks/{task_id}/call")
async def start_call_endpoint(task_id: int) -> RedirectResponse:
    await start_live_call(task_id)
    return RedirectResponse("/", status_code=303)


@app.post("/agentphone/prepare")
async def prepare_agent() -> dict[str, Any]:
    result = await AgentPhoneClient().prepare_agent_for_webhook()
    return {"ok": True, "agent": result}


@app.post("/agentphone/web-call")
async def web_call(task_id: int | None = None) -> dict[str, Any]:
    result = await AgentPhoneClient().web_call(task_id)
    return {"ok": True, "call": result}


@app.post("/agentphone/register-webhook")
async def register_webhook() -> dict[str, Any]:
    if not settings.public_base_url:
        trace("agentphone.webhook.blocked", "PUBLIC_BASE_URL/NGROK_URL missing", sponsor="AgentPhone", ok=False)
        return {"ok": False, "error": "Set PUBLIC_BASE_URL or NGROK_URL first."}
    result = await AgentPhoneClient().register_webhook(settings.public_base_url)
    return {"ok": True, "webhook": result}


@app.post("/agentphone/test-webhook")
async def test_webhook() -> dict[str, Any]:
    result = await AgentPhoneClient().test_webhook()
    return {"ok": True, "test": result}


@app.post("/agentmail/inbox")
async def agentmail_inbox() -> dict[str, Any]:
    result = await ensure_agentmail_inbox()
    return {"ok": bool(result), "inbox": result}


@app.post("/webhooks/agentphone")
async def agentphone_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    payload = await request.json()
    event = payload.get("event", "unknown")
    channel = payload.get("channel")
    log_webhook(event, channel, payload)
    trace("agentphone.webhook.received", f"{event}/{channel}", sponsor="AgentPhone", payload={"event": event, "channel": channel})

    if event == "agent.message" and channel in {"sms", "mms", "imessage"}:
        data = payload.get("data") or {}
        text = data.get("message") or ""
        requester = data.get("from")
        background_tasks.add_task(create_and_process_task, "agentphone_sms", text, requester, live=False)
        return JSONResponse({"ok": True})

    if event == "agent.message" and channel == "voice":
        return JSONResponse(voice_response(payload))

    if event == "agent.call_ended":
        data = payload.get("data") or {}
        call_id = data.get("callId") or data.get("id")
        task = find_task_by_call_id(call_id) if call_id else latest_task()
        if task:
            call_status = data.get("disconnectionReason") or data.get("status") or "ended"
            update_task(
                task["id"],
                status="completed",
                call_status=call_status,
                result_summary=json.dumps(data, default=str)[:3000],
            )
            if call_id:
                update_provider_attempt_by_call_id(
                    call_id,
                    call_status=call_status,
                    outcome=json.dumps(
                        {
                            "durationSeconds": data.get("durationSeconds"),
                            "disconnectionReason": data.get("disconnectionReason"),
                            "summary": data.get("summary"),
                            "transcript": data.get("transcript"),
                        },
                        default=str,
                    )[:1000],
                )
        return JSONResponse({"ok": True})

    return JSONResponse({"ok": True})


@app.post("/webhooks/agentmail")
async def agentmail_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    trace("agentmail.webhook.received", "Agentmail webhook received", sponsor="Agentmail", payload=payload)
    return {"ok": True}


def render_dashboard() -> str:
    tasks = list_tasks()
    events = list_events()
    env = settings.env_status()
    concepts = output_concepts()
    picks = set(final_output_picks())
    latest = tasks[0] if tasks else None
    env_html = "".join(f"<li class='{ 'on' if ok else 'off' }'><span></span>{html.escape(name)}</li>" for name, ok in env.items())
    task_cards = "".join(render_task(task) for task in tasks) or "<p class='muted'>No calls queued yet.</p>"
    event_rows = "".join(
        f"<tr><td>{html.escape(e['created_at'][11:19])}</td><td>{html.escape(e.get('sponsor') or 'System')}</td><td>{html.escape(e['event_type'])}</td><td>{html.escape(e['message'])}</td></tr>"
        for e in events[:18]
    )
    concept_cards = "".join(
        f"<article class='concept {'picked' if c['name'] in picks else ''}'><b>{html.escape(c['name'])}</b><p><strong>Pro:</strong> {html.escape(c['pro'])}</p><p><strong>Con:</strong> {html.escape(c['con'])}</p></article>"
        for c in concepts
    )
    prompt = "Use TaskRabbit, Thumbtack, Yelp, Google, and public provider sites to find a real highly rated SF home organizer or cleaning helper for a 1BR in 94109. Need weekday availability after 3pm for kitchen and closet organizing, light declutter, cleaning, and healthy meal plan/grocery support. Budget is $50-80/hour and $300 max right now. If a public phone number is found, prepare the first call. Do not book, pay, submit forms, or send messages."
    latest_json = html.escape(json.dumps(latest, indent=2, default=str)) if latest else "{}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="12">
  <title>Life Ops Concierge</title>
  <style>
    :root {{ color-scheme: dark; --bg:#090908; --paper:#f4efe4; --ink:#f7f0df; --muted:#9f9a8f; --line:#2a2822; --gold:#d8b45f; --green:#74d99f; --red:#ff786f; --blue:#8bb7ff; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at 78% 8%, rgba(216,180,95,.16), transparent 26rem), var(--bg); color:var(--ink); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif; letter-spacing:0; }}
    a {{ color:inherit; }} .shell {{ display:grid; grid-template-columns: 280px 1fr; min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; border-right:1px solid var(--line); padding:28px 22px; background:rgba(9,9,8,.82); backdrop-filter: blur(18px); }}
    main {{ padding:34px clamp(22px,4vw,64px) 80px; }}
    h1,h2,h3 {{ font-family:Newsreader, Georgia, serif; font-weight:500; letter-spacing:0; margin:0; }} h1 {{ font-size:clamp(44px,6vw,92px); line-height:.9; max-width:900px; }} h2 {{ font-size:30px; margin:42px 0 18px; }} h3 {{ font-size:22px; }}
    .kicker {{ color:var(--gold); text-transform:uppercase; font-size:12px; letter-spacing:.18em; margin-bottom:14px; }} .sub {{ color:var(--muted); max-width:760px; font-size:18px; line-height:1.55; }}
    .brand {{ font-family:Newsreader, Georgia, serif; font-size:26px; line-height:1; }} .toc {{ display:grid; gap:10px; margin:30px 0; }} .toc a {{ color:var(--muted); text-decoration:none; }} .toc a:hover {{ color:var(--ink); }}
    .env {{ list-style:none; padding:0; margin:20px 0; display:grid; gap:9px; font-size:13px; color:var(--muted); }} .env li {{ display:flex; align-items:center; gap:8px; }} .env span {{ width:8px; height:8px; border-radius:50%; background:var(--red); box-shadow:0 0 16px currentColor; }} .env .on span {{ background:var(--green); }}
    .actions {{ display:grid; gap:10px; }} button,.button {{ width:100%; border:1px solid #4a4437; background:#16140f; color:var(--ink); padding:11px 12px; border-radius:7px; cursor:pointer; text-align:left; font:inherit; text-decoration:none; transition:.15s ease; }} button:hover,.button:hover {{ border-color:var(--gold); transform:translateY(-1px); }}
    .hero {{ min-height:64vh; display:flex; flex-direction:column; justify-content:center; border-bottom:1px solid var(--line); padding-bottom:32px; }} .ticker {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; background:var(--line); margin-top:36px; }} .tile {{ background:#0f0e0b; padding:18px; min-height:110px; }} .tile b {{ color:var(--gold); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }} .tile p {{ margin:12px 0 0; color:var(--muted); }}
    form.panel {{ display:grid; gap:12px; border:1px solid var(--line); background:#0f0e0b; padding:18px; border-radius:8px; }} textarea,input {{ width:100%; border:1px solid #343126; background:#080807; color:var(--ink); padding:12px; border-radius:6px; font:inherit; }} textarea {{ min-height:96px; }}
    .grid {{ display:grid; grid-template-columns:1.15fr .85fr; gap:22px; align-items:start; }} .cards {{ display:grid; gap:14px; }} .card {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:18px; }} .meta {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }} .pill {{ border:1px solid #393529; color:var(--muted); padding:4px 8px; border-radius:999px; font-size:12px; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#080807; border:1px solid var(--line); border-radius:8px; padding:14px; color:#d8d0bd; max-height:360px; overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} td {{ border-bottom:1px solid var(--line); padding:9px 8px; color:var(--muted); vertical-align:top; }} td:nth-child(3) {{ color:var(--ink); }}
    .concepts {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }} .concept {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:#0f0e0b; }} .concept.picked {{ border-color:var(--gold); background:linear-gradient(180deg, rgba(216,180,95,.12), #0f0e0b); }} .concept p {{ margin:8px 0 0; color:var(--muted); font-size:13px; line-height:1.45; }}
    .muted {{ color:var(--muted); }} .split-actions {{ display:flex; gap:10px; margin-top:14px; }} .split-actions form {{ flex:1; }}
    @media (max-width: 900px) {{ .shell {{ grid-template-columns:1fr; }} aside {{ position:relative; height:auto; }} .grid,.ticker,.concepts {{ grid-template-columns:1fr; }} h1 {{ font-size:52px; }} }}
  </style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand">Life Ops<br>Concierge</div>
    <nav class="toc">
      <a href="#queue">Call Queue</a>
      <a href="#outputs">Output Studio</a>
      <a href="#trace">Flight Recorder</a>
      <a href="#raw">Raw State</a>
    </nav>
    <ul class="env">{env_html}</ul>
    <div class="actions">
      <form method="post" action="/demo/domestic"><button>Stage SF Chore Call</button></form>
      <form method="post" action="/agentphone/register-webhook"><button>Register AgentPhone Webhook</button></form>
      <form method="post" action="/agentphone/test-webhook"><button>Test Webhook</button></form>
      <form method="post" action="/agentmail/inbox"><button>Ensure Agentmail Inbox</button></form>
    </div>
  </aside>
  <main>
    <section class="hero">
      <div class="kicker">YC x AgentPhone domestic MVP</div>
      <h1>Text a chore. Watch the phone call leave your head.</h1>
      <p class="sub">A flashy but real control room for delegated calls: Browser Use researches, Supermemory remembers, AgentPhone speaks, Agentmail packages the result, and every silent failure is logged.</p>
      <div class="ticker">
        <div class="tile"><b>Input</b><p>SMS, dashboard form, or API task.</p></div>
        <div class="tile"><b>Brain</b><p>Domestic call rules with explicit AI disclosure.</p></div>
        <div class="tile"><b>Output</b><p>Mission control, receipt card, browser voice booth.</p></div>
        <div class="tile"><b>Trace</b><p>{html.escape(str(settings.trace_path))}</p></div>
      </div>
    </section>

    <section id="queue">
      <h2>Call Queue</h2>
      <div class="grid">
        <form class="panel" method="post" action="/tasks">
          <label>Domestic call task</label>
          <textarea name="request_text">{html.escape(prompt)}</textarea>
          <input name="requester" value="Maggie">
          <label><input type="checkbox" name="live" value="true" style="width:auto"> attempt live PSTN call if ALLOW_LIVE_CALLS=true and a phone number is parsed</label>
          <button>Create Call Packet</button>
        </form>
        <div class="cards">{task_cards}</div>
      </div>
    </section>

    <section id="outputs">
      <h2>Output Studio</h2>
      <p class="sub">Ten possible hackathon output surfaces, narrowed to the final three highlighted cards.</p>
      <div class="concepts">{concept_cards}</div>
    </section>

    <section id="trace">
      <h2>Flight Recorder</h2>
      <table>{event_rows}</table>
    </section>

    <section id="raw">
      <h2>Raw State</h2>
      <pre>{latest_json}</pre>
    </section>
  </main>
</div>
</body>
</html>"""


def render_task(task: dict[str, Any]) -> str:
    research = task.get("research") or "Research pending."
    digest = task.get("digest") or ""
    call_action = ""
    if task.get("recipient_phone"):
        call_action = f"""<form method="post" action="/tasks/{task['id']}/call"><button>Start Live Call</button></form>"""
    return f"""<article class="card">
  <h3>#{task['id']} {html.escape(task.get('recipient_name') or 'Call task')}</h3>
  <div class="meta">
    <span class="pill">{html.escape(task.get('status') or '')}</span>
    <span class="pill">{html.escape(task.get('recipient_phone') or 'no phone parsed')}</span>
    <span class="pill">{html.escape(task.get('source') or '')}</span>
  </div>
  <p>{html.escape(task.get('request_text') or '')}</p>
  <pre>{html.escape((digest or research)[:1800])}</pre>
  <div class="split-actions">
    {call_action}
    <form method="post" action="/agentphone/web-call?task_id={task['id']}"><button>Mint Browser Voice Call</button></form>
  </div>
</article>"""


def render_showcase() -> str:
    init_db()
    demo = latest_demo_run()
    sf = list_provider_attempts("sf_chores", 30)
    japan = list_provider_attempts("japan_48h", 30)
    events = list_events(12)
    demo_status = demo or {
        "status": "not_started",
        "task_text": "No controlled run started yet.",
        "sms_status": "pending",
        "research_status": "pending",
        "email_status": "pending",
        "call_status": "pending",
        "vendor_reply": "",
        "approval_packet": "",
    }
    real_counts = {
        "sf_emails": sum(1 for p in sf if p.get("email_status") == "sent"),
        "sf_calls": sum(1 for p in sf if p.get("call_id")),
        "japan_emails": sum(1 for p in japan if p.get("email_status") == "sent"),
        "japan_queued_calls": sum(1 for p in japan if p.get("call_status")),
    }
    sf_rows = "".join(
        f"<tr><td>{html.escape(p['provider_name'])}</td><td>{html.escape(p.get('email_status') or '-')}</td><td>{html.escape(p.get('call_status') or '-')}</td><td>{html.escape((p.get('outcome') or '')[:160])}</td></tr>"
        for p in sf
    )
    japan_rows = "".join(
        f"<tr><td>{html.escape(p['provider_name'])}</td><td>{html.escape(p.get('email_status') or '-')}</td><td>{html.escape(p.get('call_status') or '-')}</td><td>{html.escape((p.get('outcome') or '')[:160])}</td></tr>"
        for p in japan
    )
    event_rows = "".join(
        f"<tr><td>{html.escape(e['created_at'][11:19])}</td><td>{html.escape(e.get('sponsor') or 'System')}</td><td>{html.escape(e['event_type'])}</td><td>{html.escape(e['message'])}</td></tr>"
        for e in events
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="10">
  <title>Life Ops Concierge Showcase</title>
  <style>
    :root {{ color-scheme: dark; --bg:#080807; --ink:#f7f0df; --muted:#aaa394; --line:#29261f; --gold:#d8b45f; --green:#78d99c; --red:#ff7c70; --panel:#11100d; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at 80% 10%, rgba(216,180,95,.14), transparent 24rem), var(--bg); color:var(--ink); font-family:Inter, system-ui, sans-serif; }}
    .shell {{ display:grid; grid-template-columns:300px 1fr; min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; border-right:1px solid var(--line); padding:28px 22px; background:rgba(12,11,9,.92); }}
    main {{ padding:42px clamp(24px,5vw,76px) 80px; }}
    h1,h2,h3 {{ font-family:Newsreader, Georgia, serif; font-weight:500; letter-spacing:0; margin:0; }} h1 {{ font-size:clamp(54px,7vw,104px); line-height:.88; max-width:940px; }} h2 {{ font-size:36px; margin:52px 0 16px; }} h3 {{ font-size:24px; margin-bottom:10px; }}
    p {{ color:var(--muted); line-height:1.55; }} .brand {{ font-family:Newsreader, Georgia, serif; font-size:28px; line-height:1; }} .kicker {{ color:var(--gold); text-transform:uppercase; font-size:12px; letter-spacing:.18em; margin-bottom:16px; }}
    nav {{ display:grid; gap:10px; margin:30px 0; }} nav a {{ color:var(--muted); text-decoration:none; }} nav a:hover {{ color:var(--ink); }}
    button,.button {{ border:1px solid #4a4437; background:#16140f; color:var(--ink); padding:12px; border-radius:7px; cursor:pointer; font:inherit; text-align:left; text-decoration:none; width:100%; margin-bottom:10px; }}
    button:hover,.button:hover {{ border-color:var(--gold); transform:translateY(-1px); }}
    .hero {{ min-height:62vh; display:flex; flex-direction:column; justify-content:center; border-bottom:1px solid var(--line); }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; background:var(--line); margin-top:34px; }}
    .stat {{ background:#0f0e0b; padding:18px; min-height:120px; }} .stat b {{ color:var(--gold); font-size:12px; letter-spacing:.14em; text-transform:uppercase; }} .stat span {{ display:block; font-family:Newsreader, Georgia, serif; font-size:42px; margin-top:14px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }} .card {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:20px; }}
    .rail {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:24px 0; }} .step {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:14px; min-height:118px; }} .step strong {{ color:var(--gold); display:block; margin-bottom:8px; }}
    .done {{ border-color:rgba(120,217,156,.6); }} .waiting {{ border-color:rgba(216,180,95,.65); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} td,th {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }} th {{ color:var(--gold); font-weight:500; }}
    iframe {{ width:100%; height:560px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    .approval {{ border:1px solid var(--gold); background:linear-gradient(180deg, rgba(216,180,95,.12), var(--panel)); border-radius:8px; padding:22px; }}
    @media (max-width:900px) {{ .shell,.grid,.stats,.rail {{ grid-template-columns:1fr; }} aside {{ position:relative; height:auto; }} }}
  </style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand">Life Ops<br>Concierge</div>
    <nav>
      <a href="#loop">Live Loop</a>
      <a href="#proof">Real Proof</a>
      <a href="#approval">Approval</a>
      <a href="#ledger">Email Ledger</a>
    </nav>
    <form method="post" action="/demo/e2e/start"><button>1. Simulate SMS Entry</button></form>
    <form method="post" action="/demo/e2e/reply"><button>2. Simulate Vendor Reply</button></form>
    <form method="post" action="/demo/e2e/call"><button>3. Simulate Live Call Result</button></form>
    <a class="button" href="/">Operator Console</a>
  </aside>
  <main>
    <section class="hero">
      <div class="kicker">Hackathon E2E demo</div>
      <h1>Delegate a life task. Get a yes/no decision.</h1>
      <p>The demo uses one controlled vendor reply so the full loop completes on stage. Underneath it are real AgentPhone calls, real Agentmail sends, real provider queues, and real webhook outcomes.</p>
      <div class="stats">
        <div class="stat"><b>SF emails</b><span>{real_counts['sf_emails']}</span></div>
        <div class="stat"><b>SF calls</b><span>{real_counts['sf_calls']}</span></div>
        <div class="stat"><b>Japan emails</b><span>{real_counts['japan_emails']}</span></div>
        <div class="stat"><b>Japan queued calls</b><span>{real_counts['japan_queued_calls']}</span></div>
      </div>
    </section>
    <section id="loop">
      <h2>Live Loop</h2>
      <div class="rail">
        <div class="step done"><strong>SMS</strong>{html.escape(demo_status.get('sms_status') or 'pending')}</div>
        <div class="step done"><strong>Research</strong>{html.escape(demo_status.get('research_status') or 'real provider rails ready')}</div>
        <div class="step done"><strong>Email</strong>{html.escape(demo_status.get('email_status') or 'real sends logged')}</div>
        <div class="step done"><strong>Call</strong>{html.escape(demo_status.get('call_status') or 'real calls logged')}</div>
        <div class="step waiting"><strong>Approval</strong>{html.escape(demo_status.get('status') or 'waiting')}</div>
      </div>
      <div class="grid">
        <div class="card"><h3>Task</h3><p>{html.escape(demo_status.get('task_text') or '')}</p></div>
        <div class="approval"><h3>Approval Packet</h3><p>{html.escape(demo_status.get('approval_packet') or 'Click “Simulate Vendor Reply” to show the yes/no decision moment.')}</p><p>{html.escape(demo_status.get('vendor_reply') or '')}</p></div>
      </div>
    </section>
    <section id="proof">
      <h2>Real Proof</h2>
      <div class="grid">
        <div class="card"><h3>SF Provider Queue</h3><table><tr><th>Provider</th><th>Email</th><th>Call</th><th>Outcome</th></tr>{sf_rows}</table></div>
        <div class="card"><h3>Japan Provider Queue</h3><table><tr><th>Target</th><th>Email</th><th>Call</th><th>Outcome</th></tr>{japan_rows}</table></div>
      </div>
    </section>
    <section id="approval">
      <h2>What The User Sees</h2>
      <div class="approval">
        <h3>Say yes/no</h3>
        <p>“I found one viable option: Tuesday 4pm, $75/hr, 3-hour starter session, total $225. I also have Japan dinner/spa/jazz outreach in flight. Say YES to proceed with this organizer, NO to keep searching.”</p>
      </div>
    </section>
    <section id="ledger">
      <h2>Sent Email Ledger</h2>
      <iframe src="/artifacts/2026-05-17-sent-outreach-ledger.html"></iframe>
    </section>
    <section>
      <h2>Recent Events</h2>
      <table><tr><th>Time</th><th>Sponsor</th><th>Event</th><th>Message</th></tr>{event_rows}</table>
    </section>
  </main>
</div>
</body>
</html>"""


def main() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
