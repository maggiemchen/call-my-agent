# NEXT SESSION HANDOFF — AgentPhone Call Delegator

Date: 2026-05-17
Context: YC x AgentPhone hackathon. Build window is tight. Do not re-plan from scratch.

## User Provided Everything Needed

Do not ask Maggie for more input at startup. The only likely remaining blockers are platform-side:

- AgentPhone voice/outbound-call capability for the existing number.
- AgentPhone phone-number provisioning if the current number is SMS-only.
- Billing/payment approval if AgentPhone requires paid provisioning.
- Real external communications that make commitments, bookings, purchases, or payments.

Otherwise proceed autonomously.

## Start Here

Read:

```bash
/tmp/agentphone-hackathon-review/HANDOFF.md
/tmp/agentphone-hackathon-review/plan.md
```

Then build in this repo:

```bash
cd ~/Documents/code/agentphone-call-delegator
```

## Recommended Codex Launch

Use YOLO mode. Plain sandbox is not enough for this build because it blocks external DNS/network, keyring access, package installs, sponsor APIs, deploys, GitHub API, and tunnels.

```bash
cd ~/Documents/code/agentphone-call-delegator
source ~/Documents/secrets/.env.github
source ~/Documents/secrets/.env.browser-use
source ~/Documents/secrets/.env.supermemory
source ~/Documents/secrets/.env.agentmail
source ~/Documents/secrets/.env.agentphone
codex --dangerously-bypass-approvals-and-sandbox --search
```

Prompt for new session:

```text
Read ~/Documents/code/agentphone-call-delegator/NEXT_SESSION_HANDOFF.md, /tmp/agentphone-hackathon-review/HANDOFF.md, and /tmp/agentphone-hackathon-review/plan.md. Build the domestic-call MVP first in ~/Documents/code/agentphone-call-delegator. Use Browser Use, Supermemory, Agentmail, AgentPhone, GitHub, ngrok, and Railway env/config already loaded. Do not re-plan from scratch. Ask Maggie only if blocked on AgentPhone voice/number provisioning, billing/payment, or an irreversible external action.
```

## Product Decision

Build **Life Ops Concierge**, implemented first as the **Call Delegation Agent**:

- User texts an AgentPhone number with a phone-call task.
- Backend parses intent, researches recipient, starts outbound call.
- AgentPhone handles telephony / STT / TTS.
- Claude handles call brain.
- Browser Use handles pre-call research.
- Supermemory stores per-recipient memory.
- Agentmail can send digest/confirmation if time permits.

Scope cut:

- MVP demo should be **domestic outbound call + dashboard + staged receptionist fallback**.
- Tokyo and SF chores are the two real task packs for the demo/research layer.
- Tokyo/Japanese restaurant call is stretch only after AgentPhone proves outbound `+81` and Japanese voice support.
- Do not use relationship framing anywhere public.

Hackathon story:

- Agents today can browse and email, but the real world still runs on phone calls, vendor forms, and messy follow-up.
- This app turns a vague life task into researched options, calls/messages, memory, and a final result.
- Demo the same core loop on two domains: Tokyo trip planning and SF apartment chores.

## Verified Local Setup

Works:

- Write access to `~/Documents/code/agentphone-call-delegator`
- `uv`, `python3`, `node`, `npm`, `bun`, `railway`, `gh`, `curl`, `jq`, `sqlite3`
- `ngrok` installed: `ngrok version 3.39.2`
- `cloudflared` installed: `2026.3.0`
- Railway logged in as `manqian.ut@gmail.com`
- GitHub CLI works outside sandbox / YOLO as `maggiemchen`
- Local FastAPI/uvicorn smoke test worked on `127.0.0.1:8765`

YOLO/network verification already passed:

- `pip install fastapi uvicorn httpx pydantic python-dotenv browser-use-sdk` succeeded
- Browser Use API reachable
- Supermemory reachable
- Railway reachable

Plain sandbox failures:

- DNS fails for GitHub, Browser Use, Supermemory, Railway, PyPI
- 1Password and GitHub keyring fail in sandbox
- Use YOLO for the real build

## Credentials Prepared

These dotenv files exist and are mode `600`:

```bash
~/Documents/secrets/.env.github        # exports GH_TOKEN and GITHUB_TOKEN
~/Documents/secrets/.env.browser-use   # exports BROWSER_USE_API_KEY
~/Documents/secrets/.env.supermemory   # exports SUPERMEMORY_API_KEY
~/Documents/secrets/.env.agentmail     # exports AGENTMAIL_API_KEY
~/Documents/secrets/.env.agentphone    # exports AGENTPHONE_API_KEY, AGENTPHONE_AGENT_ID, AGENTPHONE_PHONE_NUMBER_ID, AGENTPHONE_PHONE_NUMBER
```

AgentPhone IDs discovered by read-only API lookup:

```bash
AGENTPHONE_AGENT_ID="cmpabpfww002110pjbtig3i79"
AGENTPHONE_PHONE_NUMBER_ID="cmpabpht8002310pj3gqtgatd"
AGENTPHONE_PHONE_NUMBER="+19789066281"
```

Caveat: the listed number is `status=active`, `country=US`, `type=sms`. Before using it for a voice-call demo, verify whether this project/number can place outbound calls or whether a voice-enabled number must be provisioned.

Optional, only if booth/key is available:

```bash
export SPONGE_API_KEY="..."
```

## User Constraints For Demo Tasks

Tokyo 48-hour experience planner:

- Dates: late June or early September; if exact dates are needed, optimize for either of those windows.
- Party size: 2.
- Food constraints/allergies: none.
- Hotel/neighborhood: unknown; optimize for novelty, whimsy, playfulness, and efficient transit.
- Avoid tourist traps. Bias toward Kichijoji, Nakano, Kagurazaka, Nishi-Ogikubo, Shimokitazawa/Koenji, or another tight cluster if research shows a better non-touristy route.
- Desired feel: cultural, artful, authentic, hidden jazz bars, unusual restaurants, spa/massage/recharge.
- Budget: $1000 total.
- Communication permission: act as Maggie. Do not phrase outreach as "Maggie's assistant" unless a vendor explicitly requires third-party disclosure.

SF chores / life-ops task:

- Location: 94109, San Francisco.
- Apartment: 1BR, elevator, no special access constraints.
- Timing: weekdays after 3pm, not late at night.
- Scope: organize kitchen and closet, declutter, clean, healthy meal plan/grocery support.
- Vendor quality rule: at least 10 reviews and 4.8+ stars, or 50+ reviews and 4.5+ stars.
- Budget: $50-80/hour, $300 max right now.
- Browser/account permission: may use TaskRabbit, Thumbtack, Yelp, and Google accounts via browser login.
- Outreach permission: may message providers automatically. Tone should sound natural and like Maggie, not corporate or agentic.
- Payment/booking rule: do not pay, book, or charge a card without explicit confirmation.

## Browser Use Notes

Use Browser Use Cloud SDK v3:

```bash
pip install --upgrade browser-use-sdk
```

Python shape:

```python
from browser_use_sdk.v3 import AsyncBrowserUse

client = AsyncBrowserUse(api_key=os.environ["BROWSER_USE_API_KEY"])
result = await client.run("research this business phone number and hours", model="claude-sonnet-4.6")
```

Docs:

- `https://docs.browser-use.com/cloud/llms.txt`
- `https://docs.browser-use.com/cloud/llms-full.txt`

## Build Plan

## First 30 Minutes In Next Session

1. Verify env and repo:
   - `pwd`
   - `git status --short`
   - `source` all env files from the launch block if not already loaded.
   - Check required env vars are present without printing values.

2. Verify AgentPhone capability before architecture work:
   - Read AgentPhone docs/API quickly.
   - `GET /v1/agents` and `GET /v1/numbers`.
   - Check calls API shape and whether the current `type=sms` number can place outbound calls.
   - If not, try to provision/attach a voice-capable number unless billing/payment blocks it.

3. Build smallest vertical slice:
   - FastAPI app with `GET /health`, `GET /`, SQLite state, and `POST /webhooks/agentphone`.
   - AgentPhone client wrapper for calls/messages/events.
   - One `Task` model: requested text, recipient, objective, status, research, call result.

4. Prove live plumbing:
   - Start local server.
   - Expose with `ngrok http 8000`.
   - Register webhook in AgentPhone.
   - Send/receive a test SMS or webhook event.
   - Run one safe staged call if voice works.

5. Only after plumbing works, add Browser Use + Supermemory + Agentmail:
   - Browser Use researches target.
   - Supermemory stores target/task memory.
   - Agentmail sends final digest if easy.

Do not spend the first hour making a beautiful UI. Dashboard can be plain but must show task state, events, transcript/result, and next action.

1. Scaffold FastAPI app:
   - `POST /webhooks/agentphone`
   - `GET /health`
   - `GET /` simple live dashboard
   - SQLite state for tasks/calls/events/transcripts

2. AgentPhone client:
   - Incoming SMS/call webhook parser
   - Outbound call starter
   - Event logging for `agent.message`, `agent.call_ended`, etc.
   - Voice response path must be fast; return immediately or keep under webhook timeout.

3. Call task parser:
   - Text in: “call X and ask Y”
   - Extract recipient, requested action, constraints, callback/user number.
   - Store task.

4. Research:
   - Browser Use pre-call research for phone number, hours, policy, context.
   - Cache summary in SQLite.
   - Add/read recipient memory from Supermemory.

5. Call brain:
   - Claude system prompt for receptionist/IVR/human.
   - Must disclose “calling on behalf of Maggie” and not claim to be human.
   - Handles voicemail with a concise message.
   - Escalates auth-sensitive moments back to user.

6. User updates:
   - Text result back via AgentPhone.
   - Dashboard shows timeline: requested -> researched -> calling -> result.
   - Agentmail digest/confirmation optional.

7. Tunnel/deploy:
   - First try local:
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port 8000
     ngrok http 8000
     ```
   - If ngrok flakes, Railway deploy.

## Demo Strategy

Primary:

- Domestic restaurant/vendor/dentist-style call.
- Use SF chores as the primary real task because it avoids international calling and shows immediate value.
- Show text request, dashboard research/call status, result text/email.

Fallback:

- Friend/staged receptionist call to prove the agent can complete the conversation.
- If AgentPhone voice is blocked, demo SMS/email/vendor outreach plus the dashboard/event log, and explain voice as the intended sponsor integration.

Stretch:

- Tokyo restaurant only if AgentPhone supports `+81` outbound and Japanese voice.
- Tokyo research pack should still be built as a compelling Browser Use output even if no international call is placed.

## Do Not Do Without Maggie

- Do not pay, book, or charge a card.
- Do not confirm a vendor appointment unless Maggie has approved the exact provider/time.
- Do not contact medical, financial, government, or landlord services.
- Do not force-push or delete project files.
- Public GitHub PR/issue comments on repos not owned by Maggie require approval.

## Known Security Note

During setup, `gh auth status --show-token` printed tokens into the local Codex session output. Rotate GitHub token after the hackathon if desired.
