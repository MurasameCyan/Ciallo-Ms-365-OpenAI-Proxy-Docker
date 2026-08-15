"""Bisect what makes the signed-in admin console recalc style ~1350x/s while idle.

    ADMIN_PW=... uv run python tests/manual/bisect_admin_restyle.py URL [seconds]

Established by profile_admin_cpu.py: the cost is not JS (ScriptDuration 1 ms
over 10 s), not layout (34 ms), and not the GPU-side blur that dominated the
login views. It is RecalcStyleDuration -- 9569 ms of 10 s, one whole core --
and freezing every animation did not reduce it.

So this walks a series of mutations on one loaded page, measuring
RecalcStyleDuration after each. That metric is used as the signal instead of
process CPU because it is the thing being explained and it barely varies between
runs, while whole-tree CPU on this page swung 98-181% for an unchanged variant.

Mutations are cumulative and ordered cheapest-to-most-destructive, so the first
one that collapses the number names the cause.
"""
from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

# Each step returns a short note about what it did, so a no-op is visible.
STEPS = [
    ("baseline", "() => 'as deployed'"),
    ("cancel all animations", """() => {
        const a = document.getAnimations();
        a.forEach(x => x.cancel());
        return a.length + ' cancelled';
    }"""),
    ("drop :has() rules", """() => {
        let n = 0;
        for (const sheet of document.styleSheets) {
          let rules; try { rules = sheet.cssRules } catch (e) { continue }
          for (let i = rules.length - 1; i >= 0; i--) {
            if ((rules[i].selectorText || '').includes(':has(')) { sheet.deleteRule(i); n++ }
          }
        }
        return n + ' rules';
    }"""),
    ("drop backdrop-filter", """() => {
        const s = document.createElement('style');
        s.textContent = '*{backdrop-filter:none!important;-webkit-backdrop-filter:none!important}';
        document.head.appendChild(s);
        return 'override added';
    }"""),
    ("drop transitions", """() => {
        const s = document.createElement('style');
        s.textContent = '*,*::before,*::after{transition:none!important}';
        document.head.appendChild(s);
        return 'override added';
    }"""),
    ("hide the orb", """() => {
        document.querySelectorAll('.orb').forEach(e => e.style.display = 'none');
        return document.querySelectorAll('.orb').length + ' orbs';
    }"""),
    ("empty the body", """() => {
        document.body.innerHTML = '<p>emptied</p>';
        return 'cleared';
    }"""),
]


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    password = os.environ.get("ADMIN_PW", "")
    if not password:
        print("set ADMIN_PW in the environment", file=sys.stderr)
        return 2

    with sync_playwright() as p:
        launch = {"headless": False, "args": ["--force-device-scale-factor=1"]}
        try:
            browser = p.chromium.launch(channel="chrome", **launch)
        except Exception:
            browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        cdp = page.context.new_cdp_session(page)
        cdp.send("Performance.enable")
        page.goto(f"{url}/admin", wait_until="load")
        page.fill("#pw", password)
        page.click("#btn")
        page.wait_for_selector(".brand", timeout=30000)
        page.wait_for_timeout(3000)

        def metrics() -> dict[str, float]:
            return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

        print(f"\n=== {url}/admin  (signed in)   {seconds:.0f}s per step, cumulative ===")
        print(f"  {'after this mutation':<26}{'restyle':>8} {'recalc':>8} {'layout':>8}   note")
        for label, js in STEPS:
            note = page.evaluate(js)
            page.wait_for_timeout(1500)  # let the mutation settle before sampling
            m0 = metrics()
            page.wait_for_timeout(int(seconds * 1000))
            m1 = metrics()
            recalc_ms = (m1.get("RecalcStyleDuration", 0) - m0.get("RecalcStyleDuration", 0)) * 1000
            layout_ms = (m1.get("LayoutDuration", 0) - m0.get("LayoutDuration", 0)) * 1000
            per_s = (m1.get("RecalcStyleCount", 0) - m0.get("RecalcStyleCount", 0)) / seconds
            print(f"  {label:<26}{per_s:7.0f}/s {recalc_ms / (seconds * 1000) * 100:6.0f}% {layout_ms / (seconds * 1000) * 100:6.0f}%   {note}")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
