from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db, trace, update_task
from app.services import build_digest


TASK_ID = 3

RESEARCH = """1. BEST_CALL_TARGET: NEAT Method San Francisco, +1 415-309-8212, https://neatmethod.com/locations/ca/san-francisco, first call because they explicitly serve San Francisco, list kitchens/closets/home organization as core services, and publish a local phone number.

2. SHORTLIST:
- NEAT Method San Francisco. Public phone: 415.309.8212. Source: official location page. Fit: strong for kitchen, closet, declutter, and home organization. Caveat: published hours are Mon-Fri 9am-5pm, so Sunday call likely reaches voicemail; pricing may exceed $300 because NEAT's FAQ says typical single-space services can start around $1,500-$2,500.
- Artful Organizing SF. Public phone: (415) 265-7581. Source: public business listing and website. Fit: kitchens, pantries, closets, garages, living spaces. Caveat: visible listing found 5 reviews, below Maggie's original review threshold.
- NEATNIK. Public email/contact: info@neatnik.co. Source: official website. Fit: home/office declutterer/organizer serving San Francisco; starts with a short video call. Caveat: no phone found in quick research.
- Liberated Spaces. Source: official website. Fit: professional organizer in San Francisco Bay Area since 2007. Caveat: phone/review details need follow-up.
- House Fairy SF. Source: official website. Fit: luxury home service / household support, organizing, unpacking, household management. Caveat: likely premium and may exceed $300.

3. MESSAGE_DRAFTS:
Hi, I'm looking for help in a 1BR apartment in 94109. The main scope is kitchen and closet organizing, light declutter, cleaning support, and maybe healthy meal plan/grocery support. Weekdays after 3pm are best. Budget is $50-80/hour and $300 max for the first session. Do you have any availability, and is this a fit?

4. CALL_SCRIPT:
Hi, this is an AI call agent calling on behalf of Maggie. She is looking for help with a 1BR apartment in 94109: kitchen and closet organizing, light declutter, some cleaning support, and possibly healthy meal plan or grocery support. Weekdays after 3pm work best. Her first-session budget is up to $300 at $50-80 per hour. Is this something your team can help with, and what would the next step be? I cannot book or pay without Maggie confirming.

5. BLOCKERS:
- TaskRabbit and Thumbtack often require account/login and provider messaging rather than public phone calls.
- Best public phone target, NEAT Method, likely exceeds the $300 budget based on published FAQ pricing. It is still useful as a real call target to establish feasibility and ask for smaller-session or referral options.
- Because today is Sunday, many providers are closed. A call may need to leave voicemail or ask for weekday callback.
"""


def main() -> None:
    init_db()
    fields = {
        "status": "ready_to_call",
        "recipient_name": "NEAT Method San Francisco",
        "recipient_phone": "+14153098212",
        "research": RESEARCH,
        "memory": "",
        "call_status": "unblocked with web fallback; ready for real call",
    }
    fields["digest"] = build_digest({"request_text": "SF 94109 organizer/cleaning helper", **fields})
    update_task(TASK_ID, **fields)
    trace("task.unblocked.web_fallback", "Seeded task 3 with real SF target from web fallback research", task_id=TASK_ID, payload={"recipient": fields["recipient_name"], "phone": fields["recipient_phone"]})
    print(f"Task {TASK_ID} ready: {fields['recipient_name']} {fields['recipient_phone']}")


if __name__ == "__main__":
    main()
