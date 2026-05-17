# Build Log

This file is the durable handoff for the hackathon MVP. Runtime traces go to
`logs/trace.jsonl` and SQLite state goes to `data/call_delegator.sqlite3`.

## What Was Built

- FastAPI app with `GET /health`, dashboard at `GET /`, `POST /tasks`, and
  `POST /webhooks/agentphone`.
- SQLite state for tasks, webhooks, and event traces.
- AgentPhone client for status checks, webhook registration/test, webhook-mode
  agent prep, outbound calls, and browser voice-call token minting.
- Browser Use pre-call research integration.
- Supermemory search/add integration for per-recipient/task memory.
- Agentmail inbox creation integration for digest identity.
- Domestic-call parser and staged SF chore demo.
- Flashy hackathon dashboard with:
  - Live Call Mission Control
  - Call Receipt Card
  - AgentPhone Web Booth
  - 10 output concepts with final 3 highlighted
  - Sponsor flight recorder

## Verified

- AgentPhone live API returns the configured agent and number.
- Current number is active but reports `type=sms`.
- AgentPhone voice list endpoint works.
- AgentPhone web-call token minting works, which provides a voice fallback that
  does not depend on PSTN number capability.
- AgentPhone webhook is registered to the current public tunnel and
  `/v1/webhooks/test` returned HTTP 200 through the tunnel.
- AgentPhone outbound call creation accepted the existing `type=sms` number for
  a PSTN probe to the reserved fictional `+14155550199` range; the call completed
  without contacting a real person.
- Browser Use completed a real pre-call research run for the domestic call task.
- Supermemory search works. A redirect issue on `add` was fixed with
  `follow_redirects=True`, and the direct add smoke test returned 200.
- Agentmail inbox creation works; the current inbox is
  `modernsolution183@agentmail.to`.
- Local dashboard verified at `http://127.0.0.1:8000`; current public tunnel is
  `https://open-pretty-kelly-provide.trycloudflare.com`.
- GitHub CLI auth works as `maggiemchen`; this directory is not currently a git
  repository.
- Railway CLI is available/authenticated, but this directory has no linked
  Railway project.
- `ALLOW_LIVE_CALLS=true` was enabled for the local app after user approval.
- Tokyo real-world outreach was sent through Agentmail:
  - Sweet Rain jazz bar: reservation inquiry for two guests in late June or
    early September.
  - Bulgari Hotel Tokyo Spa: spa availability/pricing inquiry for two guests in
    late June or early September.
- Agentmail returned SES message IDs and thread IDs for both Tokyo outreach
  emails.

## Not Done / Why

- No real outbound PSTN call was placed during build verification because that
  would contact an external phone number. The only PSTN probe used the reserved
  fictional `555-0199` number. The app supports real calls behind
  `ALLOW_LIVE_CALLS=true` plus an explicit live call action.
- No payment, booking, or external commitment flow was added. The call brain
  explicitly pauses at those boundaries.
- ngrok could not be used because this machine lacks an ngrok auth token
  (`ERR_NGROK_4018`). I logged that and used the installed Cloudflare quick
  tunnel instead.
- Railway deploy was not needed for the verified local+tunnel demo. It remains a
  fallback if the quick tunnel flakes.
