"""Measure the CPU the web pages burn while sitting idle.

    uv run python tests/manual/measure_web_cpu.py https://host/ [seconds]

Samples total CPU time across the launched Chrome process tree, not just the
renderer main thread. That matters here: `filter: blur()` and
`backdrop-filter` are handled off the main thread, so a page can read as 0.1%
main-thread busy while the GPU/compositor processes spin a core re-rastering a
moving blur every frame.

Only processes created by this launch are counted, so an already-running Chrome
does not pollute the numbers.
"""
from __future__ import annotations

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

_PS_LIST = "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object Id,CPU | ConvertTo-Json -Compress"


def _chrome_cpu() -> dict[int, float]:
    """pid -> cumulative CPU seconds for every running chrome process."""
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


def measure(url: str, seconds: float) -> dict:
    pre_existing = set(_chrome_cpu())
    with sync_playwright() as p:
        # Headed + installed Chrome: the headless shell skips the compositing
        # and blur work being measured.
        launch = {"headless": False, "args": ["--force-device-scale-factor=1"]}
        try:
            browser = p.chromium.launch(channel="chrome", **launch)
        except Exception:
            browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        cdp = page.context.new_cdp_session(page)
        cdp.send("Performance.enable")
        page.goto(url, wait_until="load")
        page.wait_for_timeout(2500)  # let first paint and initial fetches settle

        def _metrics() -> dict[str, float]:
            return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

        cpu_before = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m_before = _metrics()
        page.wait_for_timeout(int(seconds * 1000))
        cpu_after = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m_after = _metrics()
        browser.close()

    cpu_delta = sum(v - cpu_before.get(k, 0.0) for k, v in cpu_after.items())
    return {
        "cpu_seconds": cpu_delta,
        "cpu_pct": cpu_delta / seconds * 100,
        "procs": len(cpu_after),
        "main_thread_ms": (m_after.get("TaskDuration", 0) - m_before.get("TaskDuration", 0)) * 1000,
        "layout_count": m_after.get("LayoutCount", 0) - m_before.get("LayoutCount", 0),
        "restyle_count": m_after.get("RecalcStyleCount", 0) - m_before.get("RecalcStyleCount", 0),
    }


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

    r = measure(url, seconds)
    print(f"\n=== {url}   idle {seconds:.0f}s ===")
    print(f"  chrome processes      {r['procs']:9.0f}")
    print(f"  total CPU             {r['cpu_seconds']:9.2f} s   ->  {r['cpu_pct']:.0f}% of one core")
    print(f"  renderer main thread  {r['main_thread_ms']:9.1f} ms")
    print(f"  layout / restyle      {r['layout_count']:5.0f} / {r['restyle_count']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
