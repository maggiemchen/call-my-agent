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
  <title>Life Ops Concierge Showcase</title>
  <style>
    :root {{ color-scheme: dark; --bg:#080807; --ink:#f7f0df; --muted:#aaa394; --line:#29261f; --gold:#d8b45f; --green:#78d99c; --red:#ff7c70; --panel:#11100d; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at 80% 10%, rgba(216,180,95,.14), transparent 24rem), var(--bg); color:var(--ink); font-family:Inter, system-ui, sans-serif; }}
    .shell {{ display:grid; grid-template-columns:300px 1fr; min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; border-right:1px solid var(--line); padding:28px 22px; background:rgba(12,11,9,.92); }}
    main {{ padding:42px clamp(24px,5vw,76px) 80px; }}
    h1,h2,h3 {{ font-family:Newsreader, Georgia, serif; font-weight:500; letter-spacing:0; margin:0; }} h1 {{ font-size:clamp(48px,5.1vw,74px); line-height:.9; max-width:520px; }} h2 {{ font-size:36px; margin:52px 0 16px; }} h3 {{ font-size:24px; margin-bottom:10px; }}
    p {{ color:var(--muted); line-height:1.55; }} .brand {{ font-family:Newsreader, Georgia, serif; font-size:28px; line-height:1; }} .kicker {{ color:var(--gold); text-transform:uppercase; font-size:12px; letter-spacing:.18em; margin-bottom:16px; }}
    nav {{ display:grid; gap:10px; margin:30px 0; }} nav a {{ color:var(--muted); text-decoration:none; }} nav a:hover {{ color:var(--ink); }}
    button,.button {{ border:1px solid #4a4437; background:#16140f; color:var(--ink); padding:12px; border-radius:7px; cursor:pointer; font:inherit; text-align:left; text-decoration:none; width:100%; margin-bottom:10px; }}
    button:hover,.button:hover {{ border-color:var(--gold); transform:translateY(-1px); }}
    .hero {{ min-height:72vh; display:grid; grid-template-columns:minmax(0,440px) minmax(0,1fr); gap:24px; align-items:center; border-bottom:1px solid var(--line); padding:24px 0 42px; }}
    .hero-copy p {{ max-width:720px; font-size:18px; }}
    .hero-copy,.machine {{ min-width:0; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; background:var(--line); margin-top:34px; }}
    .stat {{ background:#0f0e0b; padding:18px; min-height:120px; }} .stat b {{ color:var(--gold); font-size:12px; letter-spacing:.14em; text-transform:uppercase; }} .stat span {{ display:block; font-family:Newsreader, Georgia, serif; font-size:42px; margin-top:14px; }}
    .machine {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:18px; min-height:540px; width:100%; max-width:540px; justify-self:start; }}
    .machine svg {{ width:100%; height:auto; display:block; }}
    .node {{ transition:opacity .28s ease, transform .28s ease, filter .28s ease; transform-origin:center; }}
    .node.dim {{ opacity:.3; }} .node.active {{ filter:drop-shadow(0 0 16px rgba(216,180,95,.75)); transform:scale(1.025); }}
    .pathline {{ stroke-dasharray:7 10; animation:flow 1.1s linear infinite; }}
    @keyframes flow {{ to {{ stroke-dashoffset:-34; }} }}
    .player {{ margin-top:24px; border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:18px; max-width:900px; }}
    .player-top {{ display:flex; gap:10px; align-items:center; justify-content:space-between; flex-wrap:wrap; }}
    .player-controls {{ display:flex; gap:10px; flex-wrap:wrap; }} .player-controls button {{ width:auto; min-width:92px; margin:0; }}
    .progress {{ height:6px; background:#222018; border-radius:999px; overflow:hidden; margin:16px 0; }} .progress span {{ display:block; width:20%; height:100%; background:var(--gold); transition:width .25s ease; }}
    .caption {{ display:grid; grid-template-columns:130px 1fr; gap:14px; align-items:start; }} .caption b {{ color:var(--gold); text-transform:uppercase; letter-spacing:.14em; font-size:12px; }} .caption strong {{ display:block; font-family:Newsreader, Georgia, serif; font-size:30px; font-weight:500; margin-bottom:6px; }}
    .story {{ display:grid; grid-template-columns:1.05fr .95fr; gap:18px; margin-top:18px; }}
    .story-card {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:18px; min-height:180px; }}
    .story-card b {{ color:var(--gold); font-size:12px; letter-spacing:.13em; text-transform:uppercase; }}
    .story-card strong {{ display:block; font-family:Newsreader, Georgia, serif; font-size:28px; font-weight:500; margin:12px 0 8px; }}
    .proof-strip {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:16px; }}
    .proof {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:14px; }}
    .proof span {{ display:block; font-family:Newsreader, Georgia, serif; font-size:34px; color:var(--ink); margin-top:8px; }}
    .lane {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:18px; margin-top:18px; }}
    .lane svg {{ width:100%; height:auto; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }} .card {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:20px; }}
    .rail {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:24px 0; }} .step {{ border:1px solid var(--line); background:#0f0e0b; border-radius:8px; padding:14px; min-height:118px; }} .step strong {{ color:var(--gold); display:block; margin-bottom:8px; }}
    .done {{ border-color:rgba(120,217,156,.6); }} .waiting {{ border-color:rgba(216,180,95,.65); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} td,th {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }} th {{ color:var(--gold); font-weight:500; }}
    iframe {{ width:100%; height:560px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    .approval {{ border:1px solid var(--gold); background:linear-gradient(180deg, rgba(216,180,95,.12), var(--panel)); border-radius:8px; padding:22px; }}
    @media (max-width:900px) {{ .shell,.grid,.stats,.rail,.hero,.story,.proof-strip {{ grid-template-columns:1fr; }} aside {{ position:relative; height:auto; }} }}
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
      <div class="hero-copy">
        <div class="kicker">Hackathon E2E demo</div>
        <h1>Text the agent. It goes into the real world.</h1>
        <p>A single SMS becomes browser research, email outreach, phone calls, voicemail handling, hour-aware retries, and finally one clean approval packet: yes/no, not another chore list.</p>
        <div class="stats">
          <div class="stat"><b>SF emails</b><span>{real_counts['sf_emails']}</span></div>
          <div class="stat"><b>SF calls</b><span>{real_counts['sf_calls']}</span></div>
          <div class="stat"><b>Japan emails</b><span>{real_counts['japan_emails']}</span></div>
          <div class="stat"><b>Japan queued calls</b><span>{real_counts['japan_queued_calls']}</span></div>
        </div>
      </div>
      <div class="machine" aria-label="Life Ops Concierge execution diagram">
        <svg viewBox="0 0 760 760" role="img">
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#d8b45f"/></marker>
            <filter id="soft"><feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#000" flood-opacity=".35"/></filter>
          </defs>
          <rect x="20" y="20" width="720" height="720" rx="18" fill="#0b0a08" stroke="#2a2822"/>
          <text x="54" y="70" fill="#d8b45f" font-size="16" font-family="Inter, sans-serif" letter-spacing="3">LIVE EXECUTION LOOP</text>
          <g class="node" data-stage="0">
            <rect x="64" y="120" width="160" height="250" rx="28" fill="#16140f" stroke="#4a4437" filter="url(#soft)"/>
            <rect x="84" y="150" width="120" height="170" rx="12" fill="#090908" stroke="#2a2822"/>
            <circle cx="144" cy="340" r="10" fill="#2a2822"/>
            <text x="104" y="185" fill="#f7f0df" font-size="18">SMS</text>
            <text x="104" y="218" fill="#aaa394" font-size="14">“Find an organizer</text>
            <text x="104" y="240" fill="#aaa394" font-size="14">and plan Japan.”</text>
          </g>
          <path class="pathline" d="M230 240 C285 240 296 170 350 170" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow)"/>
          <path class="pathline" d="M230 250 C290 260 304 310 360 330" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow)"/>
          <path class="pathline" d="M230 260 C292 305 304 470 360 505" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow)"/>
          <g class="node" data-stage="1">
            <rect x="360" y="120" width="300" height="100" rx="12" fill="#11100d" stroke="#2a2822"/>
            <text x="386" y="154" fill="#f7f0df" font-size="22" font-family="Georgia, serif">Browser research</text>
            <text x="386" y="185" fill="#aaa394" font-size="14">TaskRabbit, Yelp, provider sites, hours</text>
            <circle cx="630" cy="170" r="16" fill="#78d99c"/>
          </g>
          <g class="node" data-stage="2">
            <rect x="380" y="280" width="260" height="110" rx="12" fill="#11100d" stroke="#2a2822"/>
            <text x="406" y="314" fill="#f7f0df" font-size="22" font-family="Georgia, serif">Email fan-out</text>
            <text x="406" y="346" fill="#aaa394" font-size="14">Agentmail sends exact inquiry text</text>
            <text x="406" y="370" fill="#d8b45f" font-size="18">{real_counts['sf_emails'] + real_counts['japan_emails']} real emails</text>
          </g>
          <g class="node" data-stage="3">
            <rect x="380" y="460" width="260" height="120" rx="12" fill="#11100d" stroke="#2a2822"/>
            <text x="406" y="494" fill="#f7f0df" font-size="22" font-family="Georgia, serif">Phone calls</text>
            <text x="406" y="526" fill="#aaa394" font-size="14">AgentPhone calls, voicemails, webhooks</text>
            <text x="406" y="552" fill="#d8b45f" font-size="18">{real_counts['sf_calls']} real calls placed</text>
          </g>
          <path d="M510 220 L510 280" stroke="#d8b45f" stroke-width="3" marker-end="url(#arrow)"/>
          <path d="M510 390 L510 460" stroke="#d8b45f" stroke-width="3" marker-end="url(#arrow)"/>
          <g class="node" data-stage="4">
            <rect x="114" y="610" width="520" height="72" rx="12" fill="#1a160f" stroke="#d8b45f"/>
            <text x="145" y="640" fill="#f7f0df" font-size="24" font-family="Georgia, serif">Approval packet</text>
            <text x="145" y="665" fill="#aaa394" font-size="14">“Tuesday 4pm, $225. Say YES to proceed.”</text>
          </g>
          <path d="M380 560 C300 590 250 600 210 610" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow)"/>
          <path d="M640 335 C705 370 702 645 635 648" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow)"/>
        </svg>
      </div>
    </section>
    <section id="player" class="player">
      <div class="player-top">
        <div class="kicker">Interactive demo player</div>
        <div class="player-controls">
          <button type="button" id="prevStage">Back</button>
          <button type="button" id="playStage">Play</button>
          <button type="button" id="nextStage">Next</button>
        </div>
      </div>
      <div class="progress"><span id="stageProgress"></span></div>
      <div class="caption">
        <b id="stageLabel">Step 1</b>
        <div><strong id="stageTitle">Text the task</strong><p id="stageBody">Maggie sends one plain-English SMS. No app, no form, no workflow builder.</p></div>
      </div>
    </section>
    <section id="story">
      <h2>The Story Judges Can Follow</h2>
      <div class="story">
        <div class="story-card"><b>1. Frictionless entry</b><strong>User texts a vague life task.</strong><p>No app install, no form, no workflow setup. The phone number is the interface.</p></div>
        <div class="story-card"><b>2. Real-world work</b><strong>The agent opens channels humans use.</strong><p>It researches providers, sends emails, calls phone numbers, leaves voicemails, and respects hours.</p></div>
        <div class="story-card"><b>3. Controlled E2E proof</b><strong>A demo vendor reply completes the loop live.</strong><p>We do not wait for random businesses to reply on stage, but we show real outbound proof beside the controlled reply.</p></div>
        <div class="story-card"><b>4. One decision</b><strong>The user gets a yes/no packet.</strong><p>Not “here are twenty tabs.” The output is a recommended next action with price, time, and stop conditions.</p></div>
      </div>
      <div class="lane">
        <svg viewBox="0 0 1100 300" role="img" aria-label="Two workstreams from one SMS">
          <rect x="20" y="30" width="210" height="90" rx="10" fill="#15130f" stroke="#4a4437"/>
          <text x="48" y="67" fill="#f7f0df" font-size="24" font-family="Georgia, serif">One SMS</text>
          <text x="48" y="96" fill="#aaa394" font-size="14">organizer + Japan plan</text>
          <path d="M235 75 L335 75" stroke="#d8b45f" stroke-width="3" marker-end="url(#arrow2)"/>
          <path d="M235 75 C285 75 290 210 335 210" stroke="#d8b45f" stroke-width="3" fill="none" marker-end="url(#arrow2)"/>
          <defs><marker id="arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#d8b45f"/></marker></defs>
          <rect x="350" y="30" width="300" height="90" rx="10" fill="#11100d" stroke="#2a2822"/>
          <text x="380" y="64" fill="#f7f0df" font-size="22" font-family="Georgia, serif">SF organization lane</text>
          <text x="380" y="94" fill="#aaa394" font-size="14">emails sent, calls placed, remaining calls queued</text>
          <rect x="350" y="165" width="300" height="90" rx="10" fill="#11100d" stroke="#2a2822"/>
          <text x="380" y="199" fill="#f7f0df" font-size="22" font-family="Georgia, serif">Japan 48-hour lane</text>
          <text x="380" y="229" fill="#aaa394" font-size="14">restaurants, spa, jazz outreach in flight</text>
          <path d="M655 75 L775 135" stroke="#d8b45f" stroke-width="3" marker-end="url(#arrow2)"/>
          <path d="M655 210 L775 150" stroke="#d8b45f" stroke-width="3" marker-end="url(#arrow2)"/>
          <rect x="790" y="95" width="270" height="90" rx="10" fill="#1a160f" stroke="#d8b45f"/>
          <text x="820" y="130" fill="#f7f0df" font-size="24" font-family="Georgia, serif">Approval moment</text>
          <text x="820" y="160" fill="#aaa394" font-size="14">“Say YES, or keep searching.”</text>
        </svg>
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
<script>
  const stages = [
    ["Step 1", "Text the task", "Maggie sends one plain-English SMS. No app, no form, no workflow builder."],
    ["Step 2", "Research the real world", "The agent researches providers, hours, pricing constraints, public phones, and contact paths."],
    ["Step 3", "Email fan-out", "Agentmail sends real non-binding inquiries. The ledger below shows exact recipients and exact copy."],
    ["Step 4", "Phone calls", "AgentPhone calls real providers, handles voicemail, logs transcripts, and defers closed businesses."],
    ["Step 5", "Ask for approval", "The user receives one yes/no decision packet instead of a pile of tabs and follow-ups."]
  ];
  let stage = 0;
  let timer = null;
  const nodes = [...document.querySelectorAll(".node[data-stage]")];
  const label = document.getElementById("stageLabel");
  const title = document.getElementById("stageTitle");
  const body = document.getElementById("stageBody");
  const bar = document.getElementById("stageProgress");
  function setStage(next) {{
    stage = (next + stages.length) % stages.length;
    nodes.forEach(node => {{
      const active = Number(node.dataset.stage) === stage;
      node.classList.toggle("active", active);
      node.classList.toggle("dim", !active);
    }});
    label.textContent = stages[stage][0];
    title.textContent = stages[stage][1];
    body.textContent = stages[stage][2];
    bar.style.width = `${{((stage + 1) / stages.length) * 100}}%`;
  }}
  document.getElementById("prevStage").addEventListener("click", () => setStage(stage - 1));
  document.getElementById("nextStage").addEventListener("click", () => setStage(stage + 1));
  document.getElementById("playStage").addEventListener("click", event => {{
    if (timer) {{
      clearInterval(timer);
      timer = null;
      event.currentTarget.textContent = "Play";
      return;
    }}
    event.currentTarget.textContent = "Pause";
    timer = setInterval(() => setStage(stage + 1), 1700);
  }});
  setStage(0);
</script>
</body>
</html>"""


def main() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
