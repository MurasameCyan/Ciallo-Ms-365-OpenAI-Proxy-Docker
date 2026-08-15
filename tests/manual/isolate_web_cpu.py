"""Test whether any motion can survive cheaply on the blurred web UI.

    uv run python tests/manual/isolate_web_cpu.py URL [KEY] [seconds] [repeats]

Measured so far, idle: login view 49% of a core, signed-in user view 69%, admin
login 85%; disabling animations drops all three to ~2%. Freezing one animation
while another still runs barely helps, so the cost is not a single rule - a
fixed blurred `.orb` sits behind `backdrop-filter` cards, and any motion in that
stack forces the blurred surfaces to re-rasterise every frame.

The question this run answers: does that condemn *all* motion, or only motion
that moves blurred geometry? A blur is re-derived when its source is
transformed, but an `opacity` change should composite from the cached blurred
texture. If an opacity-only "breathe" is near-free, the UI keeps a live ambient
glow and only the rotations and gradient sweeps need to go.

CPU is sampled across the whole Chrome process tree; the renderer main thread
reads ~0% while a core spins.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys

from playwright.sync_api import sync_playwright

_PS_LIST = "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object Id,CPU | ConvertTo-Json -Compress"

_FREEZE_ALL = "*,*::before,*::after{animation:none!important}"
# Opacity-only breathe on the blurred orb, everything else frozen.
_OPACITY_ONLY = _FREEZE_ALL + """
@keyframes orbBreathe{50%{opacity:.5}}
.orb{animation:orbBreathe 5s ease-in-out infinite!important}"""
# Same idea but the thing that breathes is not blurred: the brand mark rings.
_TRANSFORM_ONLY_UNBLURRED = _FREEZE_ALL + """
.brand-mark::before,.brand-mark:before{animation:markSpin 4.8s linear infinite!important}"""

VARIANTS = {
    "as shipped": "",
    "all animations frozen": _FREEZE_ALL,
    "opacity-only orb breathe": _OPACITY_ONLY,
    "unblurred ring spin only": _TRANSFORM_ONLY_UNBLURRED,
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


def measure(url: str, seconds: float, css: str, key: str | None) -> float:
    pre_existing = set(_chrome_cpu())
    with sync_playwright() as p:
        launch = {"headless": False, "args": ["--force-device-scale-factor=1"]}
        try:
            browser = p.chromium.launch(channel="chrome", **launch)
        except Exception:
            browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        if key:
            page.goto(url, wait_until="domcontentloaded")
            page.evaluate("k => sessionStorage.setItem('user_api_key', k)", key)
        page.goto(url, wait_until="load")
        if css:
            page.add_style_tag(content=css)
        page.wait_for_timeout(3000)

        before = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        page.wait_for_timeout(int(seconds * 1000))
        after = {k: v for k, v in _chrome_cpu().items() if k not in pre_existing}
        browser.close()

    return sum(v - before.get(k, 0.0) for k, v in after.items()) / seconds * 100


def main() -> int:
    url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
    repeats = int(sys.argv[4]) if len(sys.argv) > 4 else 2

    target = f"{url}/"
    print(f"\n=== {target}{'  (signed in)' if key else '  (login view)'}   idle {seconds:.0f}s x{repeats}, median ===")
    for label, css in VARIANTS.items():
        runs = sorted(measure(target, seconds, css, key) for _ in range(repeats))
        print(f"  {label:<28}{statistics.median(runs):6.0f}%  [{runs[0]:.0f}-{runs[-1]:.0f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
