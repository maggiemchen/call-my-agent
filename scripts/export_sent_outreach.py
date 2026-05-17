from __future__ import annotations

import html
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db import init_db
from scripts.run_real_world_outreach import SF_PROVIDERS, sf_email_text
from scripts.send_tokyo_outreach import TARGETS as INITIAL_TOKYO_TARGETS
from scripts.run_japan_execution_queue import TARGETS as JAPAN_TARGETS, email_text as japan_email_text


OUT = Path("artifacts/2026-05-17-sent-outreach-ledger.html")


def sent_provider_rows() -> list[dict[str, str]]:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select provider_name, domain, email, email_status, outcome, website
        from provider_attempts
        where email_status = 'sent'
        order by domain, provider_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def body_for(row: dict[str, str]) -> str:
    if row["domain"] == "sf_chores":
        provider = next((p for p in SF_PROVIDERS if p["name"] == row["provider_name"]), None)
        return sf_email_text(provider["name"] if provider else row["provider_name"])
    target = next((t for t in JAPAN_TARGETS if t["name"] == row["provider_name"]), None)
    if target:
        return japan_email_text(target)
    target = next((t for t in INITIAL_TOKYO_TARGETS if t["name"] == row["provider_name"]), None)
    if target:
        return target["text"]
    return "Body not found in local scripts."


def render() -> str:
    init_db()
    rows = sent_provider_rows()
    cards = []
    for row in rows:
        body = body_for(row)
        cards.append(
            f"""
            <article class="card">
              <div class="meta">{html.escape(row['domain'])}</div>
              <h2>{html.escape(row['provider_name'])}</h2>
              <p><strong>To:</strong> {html.escape(row.get('email') or '')}</p>
              <p><strong>Status:</strong> {html.escape(row.get('email_status') or '')}</p>
              <p><strong>Message ID / thread:</strong> {html.escape(row.get('outcome') or '')}</p>
              <pre>{html.escape(body)}</pre>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sent Outreach Ledger</title>
  <style>
    :root {{ color-scheme: dark; --bg:#090908; --ink:#f7f0df; --muted:#aaa394; --line:#2b2821; --gold:#d6b05b; --panel:#11100d; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Inter, system-ui, sans-serif; }}
    .shell {{ display:grid; grid-template-columns:280px 1fr; min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; border-right:1px solid var(--line); padding:28px 22px; background:#0d0c0a; }}
    main {{ padding:40px clamp(24px,5vw,72px) 80px; }}
    h1,h2 {{ font-family:Newsreader, Georgia, serif; font-weight:500; margin:0; letter-spacing:0; }}
    h1 {{ font-size:64px; line-height:.95; max-width:850px; }} h2 {{ font-size:28px; }}
    p {{ color:var(--muted); line-height:1.5; }}
    .brand {{ font-family:Newsreader, Georgia, serif; font-size:26px; line-height:1; }}
    .kicker,.meta {{ color:var(--gold); text-transform:uppercase; font-size:12px; letter-spacing:.16em; margin-bottom:12px; }}
    .card {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:20px; margin:18px 0; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#080807; border:1px solid var(--line); border-radius:8px; padding:16px; color:#ddd4c0; line-height:1.45; }}
    @media (max-width:900px) {{ .shell {{ grid-template-columns:1fr; }} aside {{ position:relative; height:auto; }} h1 {{ font-size:44px; }} }}
  </style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand">Life Ops<br>Concierge</div>
    <p>Exact outbound email text reconstructed from the scripts that sent the messages, plus DB message/thread IDs.</p>
  </aside>
  <main>
    <div class="kicker">Audit trail</div>
    <h1>Sent outreach ledger.</h1>
    <p>Every card below is an external email that has been sent or whose sent state is recorded in the local provider queue.</p>
    {''.join(cards) or '<p>No sent outreach rows found.</p>'}
  </main>
</div>
</body>
</html>"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
