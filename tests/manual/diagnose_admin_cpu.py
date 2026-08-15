"""Find what actually burns CPU on the signed-in admin console.

    ADMIN_PW=... uv run python tests/manual/diagnose_admin_cpu.py URL [seconds]

Freezing the ambient decor took the login views from ~50-85% of a core to ~1%,
but the signed-in console still sits at ~172%. So something else dominates
there. This dumps, over an idle window: which animations are still running,
how much of the cost is the renderer main thread (JS/layout) versus the rest of
the process tree (GPU/compositor), and every timer and fetch the page starts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

_PS_LIST = "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object Id,CPU | ConvertTo-Json -Compress"

# Installed before any page script so nothing is missed.
_HOOK_JS = """
window.__probe = {intervals: [], timeouts: 0, raf: 0, fetches: []};
const si = window.setInterval;
window.setInterval = function (fn, ms, ...rest) {
  window.__probe.intervals.push({ms: ms, src: String(fn).slice(0, 90).replace(/\\s+/g, ' ')});
  return si.call(this, fn, ms, ...rest);
};
const st = window.setTimeout;
window.setTimeout = function (...a) { window.__probe.timeouts++; return st.apply(this, a) };
const rq = window.requestAnimationFrame;
window.requestAnimationFrame = function (...a) { window.__probe.raf++; return rq.apply(this, a) };
const f = window.fetch;
window.fetch = function (u, ...rest) {
  window.__probe.fetches.push(String(typeof u === 'string' ? u : u.url).slice(0, 70));
  return f.call(this, u, ...rest);
};
"""

_ANIM_JS = """() => document.getAnimations().map(a => ({
  name: a.animationName || (a.effect && a.effect.getKeyframes && 'css') || '?',
  target: (() => {
    const t = a.effect && a.effect.target;
    if (!t) return '?';
    const ps = a.effect.pseudoElement || '';
    return (t.tagName || '').toLowerCase() + (t.className ? '.' + String(t.className).split(' ')[0] : '') + ps;
  })(),
  state: a.playState,
}))"""


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


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
    password = os.environ.get("ADMIN_PW", "")
    if not password:
        print("set ADMIN_PW in the environment", file=sys.stderr)
        return 2

    pre_existing = set(_chrome_cpu())
    with sync_playwright() as p:
        launch = {"headless": False, "args": ["--force-device-scale-factor=1"]}
        try:
            browser = p.chromium.launch(channel="chrome", **launch)
        except Exception:
            browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(_HOOK_JS)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Performance.enable")
        page.goto(f"{url}/admin", wait_until="load")
        page.fill("#pw", password)
        page.click("#btn")
        page.wait_for_selector(".brand", timeout=30000)
        page.wait_for_timeout(4000)

        def metrics() -> dict[str, float]:
            return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

        anims = page.evaluate(_ANIM_JS)
        probe_before = page.evaluate("() => ({t: window.__probe.timeouts, r: window.__probe.raf, f: window.__probe.fetches.length})")
        cpu_before = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m_before = metrics()

        page.wait_for_timeout(int(seconds * 1000))

        cpu_after = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        m_after = metrics()
        probe = page.evaluate("() => window.__probe")
        node_count = page.evaluate("() => document.getElementsByTagName('*').length")
        blurred = page.evaluate("""() => {
          let n = 0, bd = 0;
          for (const el of document.getElementsByTagName('*')) {
            const s = getComputedStyle(el);
            if (s.filter && s.filter.includes('blur')) n++;
            if ((s.backdropFilter || s.webkitBackdropFilter || '').includes('blur')) bd++;
          }
          return {filter_blur: n, backdrop: bd};
        }""")
        browser.close()

    cpu = sum(v - cpu_before.get(k, 0.0) for k, v in cpu_after.items())
    main_ms = (m_after.get("TaskDuration", 0) - m_before.get("TaskDuration", 0)) * 1000

    print(f"\n=== {url}/admin  (signed in)   idle {seconds:.0f}s ===")
    print(f"  total CPU            {cpu / seconds * 100:6.0f}% of one core   ({cpu:.1f}s over {len(cpu_after)} procs)")
    print(f"  renderer main thread {main_ms / (seconds * 1000) * 100:6.0f}% of one core   ({main_ms:.0f} ms)")
    print(f"  layout / restyle     {m_after.get('LayoutCount', 0) - m_before.get('LayoutCount', 0):.0f}"
          f" / {m_after.get('RecalcStyleCount', 0) - m_before.get('RecalcStyleCount', 0):.0f}")
    print(f"  DOM nodes            {node_count:6.0f}   filter:blur x{blurred['filter_blur']}, backdrop-filter x{blurred['backdrop']}")
    print(f"  timers during window  timeouts +{probe['timeouts'] - probe_before['t']}, "
          f"rAF +{probe['raf'] - probe_before['r']}, fetches +{len(probe['fetches']) - probe_before['f']}")
    print(f"\n  animations still running: {len(anims)}")
    for a in anims:
        print(f"    {a['name']:<24} on {a['target']:<34} {a['state']}")
    print(f"\n  setInterval registered: {len(probe['intervals'])}")
    for iv in probe["intervals"]:
        print(f"    every {iv['ms']:>7} ms   {iv['src']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
