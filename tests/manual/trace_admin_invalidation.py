"""Ask Chrome why the idle admin console keeps invalidating style.

    ADMIN_PW=... uv run python tests/manual/trace_admin_invalidation.py URL [seconds]

bisect_admin_restyle.py ruled out the obvious candidates: cancelling every
animation, deleting all 16 :has() rules, killing backdrop-filter, killing
transitions and hiding the orb each left the cost intact -- recalc stayed near a
full core while restyle/s climbed from 1537 to 4082, i.e. each pass got cheaper
and the loop just ran more often. Only emptying <body> stopped it. That shape is
a self-sustaining invalidation loop, not a 60 Hz animation.

So this captures the tracing category DevTools itself uses to explain
"Recalculate Style" and prints the invalidation reasons and the nodes they name.
"""
from __future__ import annotations

import collections
import json
import os
import sys

from playwright.sync_api import sync_playwright

_CATEGORIES = [
    "-*",
    "devtools.timeline",
    "disabled-by-default-devtools.timeline",
    "disabled-by-default-devtools.timeline.invalidationTracking",
]


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    password = os.environ.get("ADMIN_PW", "")
    if not password:
        print("set ADMIN_PW in the environment", file=sys.stderr)
        return 2

    events: list[dict] = []
    with sync_playwright() as p:
        launch = {"headless": False, "args": ["--force-device-scale-factor=1"]}
        try:
            browser = p.chromium.launch(channel="chrome", **launch)
        except Exception:
            browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        cdp = page.context.new_cdp_session(page)
        page.goto(f"{url}/admin", wait_until="load")
        page.fill("#pw", password)
        page.click("#btn")
        page.wait_for_selector(".brand", timeout=30000)
        page.wait_for_timeout(3000)

        cdp.on("Tracing.dataCollected", lambda ev: events.extend(ev.get("value", [])))
        done = []
        cdp.on("Tracing.tracingComplete", lambda ev: done.append(True))
        cdp.send("Tracing.start", {
            "traceConfig": {"includedCategories": _CATEGORIES, "recordMode": "recordAsMuchAsPossible"},
            "transferMode": "ReportEvents",
        })
        page.wait_for_timeout(int(seconds * 1000))
        cdp.send("Tracing.end")
        for _ in range(40):
            if done:
                break
            page.wait_for_timeout(250)
        browser.close()

    names = collections.Counter(e.get("name", "?") for e in events)
    print(f"\n=== {url}/admin  (signed in)   traced {seconds:.0f}s idle ===")
    print(f"  {len(events)} trace events\n")
    print("  event counts (top 15):")
    for name, n in names.most_common(15):
        print(f"    {n:7d}  {name}")

    reasons: collections.Counter = collections.Counter()
    for e in events:
        if "Invalidation" not in e.get("name", ""):
            continue
        d = e.get("args", {}).get("data", {})
        reason = d.get("reason") or d.get("invalidationSet") or "?"
        node = d.get("nodeName") or d.get("nodeId") or ""
        extra = d.get("changedAttribute") or d.get("changedClass") or d.get("changedId") or d.get("selectorPart") or ""
        reasons[(e["name"], str(reason), str(node)[:44], str(extra)[:26])] += 1

    print(f"\n  invalidation reasons (top 20 of {sum(reasons.values())}):")
    for (ev_name, reason, node, extra) in [k for k, _ in reasons.most_common(20)]:
        n = reasons[(ev_name, reason, node, extra)]
        print(f"    {n:6d}  {ev_name:<34} {reason:<30} {node:<44} {extra}")

    if not reasons:
        # No invalidation records means style is being recalculated without any
        # DOM/CSS trigger -- dump one raw UpdateLayoutTree so the cause is visible.
        for e in events:
            if e.get("name") in ("UpdateLayoutTree", "RecalculateStyles", "ScheduleStyleRecalculation"):
                print("\n  sample raw event:")
                print("   ", json.dumps(e, indent=2)[:1400])
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
