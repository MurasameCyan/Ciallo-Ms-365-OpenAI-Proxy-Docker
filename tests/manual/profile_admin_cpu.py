"""Profile the signed-in admin console while it sits idle.

    ADMIN_PW=... uv run python tests/manual/profile_admin_cpu.py URL [seconds]

The CSS-variant sweep in measure_admin_cpu.py came back flat: freezing every
animation and stripping every backdrop-filter changed nothing, while the
renderer main thread stayed pinned near 100% and style recalcs held at ~1000/s.
That rules out the decoration this page shares with the login views, so stop
guessing at CSS and ask the profiler which function is actually running.

Prints where the main thread's time goes (script / style / layout, from
Performance.getMetrics) and the heaviest call stacks (from the sampling
profiler), so a JS culprit shows up by name and a non-JS one shows up as
(program)/(garbage collector).
"""
from __future__ import annotations

import collections
import os
import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
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
        cdp.send("Profiler.enable")
        page.goto(f"{url}/admin", wait_until="load")
        page.fill("#pw", password)
        page.click("#btn")
        page.wait_for_selector(".brand", timeout=30000)
        page.wait_for_timeout(4000)

        def metrics() -> dict[str, float]:
            return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

        cdp.send("Profiler.setSamplingInterval", {"interval": 200})
        m0 = metrics()
        cdp.send("Profiler.start")
        page.wait_for_timeout(int(seconds * 1000))
        prof = cdp.send("Profiler.stop")["profile"]
        m1 = metrics()
        browser.close()

    print(f"\n=== {url}/admin  (signed in)   idle {seconds:.0f}s ===")
    print("  main-thread time, by kind (% of one core):")
    for name in ("TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "DevToolsCommandDuration"):
        d = m1.get(name, 0) - m0.get(name, 0)
        print(f"    {name:<24}{d / seconds * 100:6.1f}%   ({d * 1000:.0f} ms)")
    for name in ("LayoutCount", "RecalcStyleCount", "Nodes", "JSEventListeners", "LayoutObjects"):
        d = m1.get(name, 0) - m0.get(name, 0)
        print(f"    {name:<24}{d:8.0f} delta   (now {m1.get(name, 0):.0f})")

    nodes = {n["id"]: n for n in prof["nodes"]}
    self_time: dict[int, int] = collections.Counter()
    for sample in prof.get("samples", []):
        self_time[sample] += 1
    total = sum(self_time.values()) or 1

    def label(node_id: int) -> str:
        cf = nodes[node_id]["callFrame"]
        fn = cf.get("functionName") or "(anonymous)"
        src = (cf.get("url") or "").rsplit("/", 1)[-1]
        line = cf.get("lineNumber", -1)
        return f"{fn} @ {src}:{line}" if src else fn

    print(f"\n  heaviest stacks ({total} samples):")
    for node_id, n in self_time.most_common(12):
        # Walk up two frames so a hot leaf shows who called it.
        parents = []
        for cand in prof["nodes"]:
            for child in cand.get("children", []):
                if child == node_id:
                    parents.append(cand["id"])
        caller = f"   <- {label(parents[0])}" if parents else ""
        print(f"    {n / total * 100:5.1f}%  {label(node_id)}{caller}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
