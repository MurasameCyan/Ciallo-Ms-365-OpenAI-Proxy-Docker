"""Locate the idle CPU cost on the signed-in admin console.

    ADMIN_PW=... uv run python tests/manual/measure_admin_cpu.py URL [seconds] [repeats]

Freezing the ambient decor took the login views from 49-85% of a core to ~1%,
but the signed-in console still sits at ~170%, with the renderer main thread
alone at ~108% and ~1000 style recalcs per second. So this page has a different
bottleneck and each candidate has to be measured, not reasoned about.

The page cannot be reached without logging in, so the password is read from
$ADMIN_PW and never reaches argv or the terminal. Variants are applied as extra
stylesheets on the live page, one browser per variant so the CPU sample covers
only that variant's process tree.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys

from playwright.sync_api import sync_playwright

_PS_LIST = "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object Id,CPU | ConvertTo-Json -Compress"

# `.active` on a nav item is not an interaction state -- it marks the current
# page, so the selected tab animates forever.
_NO_NAV_FLOW = ".nav-item.active::after,.nav-item.active:after{animation:none!important}"
_FREEZE_ALL = "*,*::before,*::after{animation:none!important}"
# 37 elements carry backdrop-filter on this page; each is re-derived whenever
# anything above or below it changes.
_NO_BACKDROP = "*{backdrop-filter:none!important;-webkit-backdrop-filter:none!important}"
# `:has()` invalidates style for every ancestor when a descendant changes.
_NO_HAS = ".card:has(details[open])::after,.debug-gate-card:has(.debug-gate.on)::after{animation:none!important;content:none!important}"

VARIANTS = {
    "as deployed": "",
    "+ nav-item.active frozen": _NO_NAV_FLOW,
    "+ all animation frozen": _FREEZE_ALL,
    "+ all anim, no backdrop": _FREEZE_ALL + _NO_BACKDROP,
    "no backdrop only": _NO_BACKDROP,
}


def _chrome_cpu() -> dict[int, float]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _PS_LIST],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return {}
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    return {int(p["Id"]): float(p["CPU"] or 0.0) for p in data if p.get("Id")}


def measure(url: str, seconds: float, css: str, password: str) -> tuple[float, float, int]:
    """Returns (whole-tree CPU %, renderer main-thread %, restyle count)."""
    pre_existing = set(_chrome_cpu())
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
        if css:
            page.add_style_tag(content=css)
        page.wait_for_timeout(4000)

        def metrics() -> dict[str, float]:
            return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

        before = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m0 = metrics()
        page.wait_for_timeout(int(seconds * 1000))
        after = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m1 = metrics()
        browser.close()

    cpu = sum(v - before.get(k, 0.0) for k, v in after.items()) / seconds * 100
    main = (m1.get("TaskDuration", 0) - m0.get("TaskDuration", 0)) / seconds * 100
    restyle = int(m1.get("RecalcStyleCount", 0) - m0.get("RecalcStyleCount", 0))
    return cpu, main, restyle


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
    repeats = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    password = os.environ.get("ADMIN_PW", "")
    if not password:
        print("set ADMIN_PW in the environment", file=sys.stderr)
        return 2

    print(f"\n=== {url}/admin  (signed in)   idle {seconds:.0f}s x{repeats}, median ===")
    print(f"  {'variant':<28}{'CPU':>6}  {'main':>6}  {'restyle/s':>10}")
    for label, css in VARIANTS.items():
        runs = [measure(url, seconds, css, password) for _ in range(repeats)]
        cpu = sorted(r[0] for r in runs)
        main_pct = statistics.median(r[1] for r in runs)
        restyle = statistics.median(r[2] for r in runs) / seconds
        print(f"  {label:<28}{statistics.median(cpu):5.0f}%  {main_pct:5.0f}%  {restyle:9.0f}   [{cpu[0]:.0f}-{cpu[-1]:.0f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
