from __future__ import annotations

from pathlib import Path


_SRC = Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy"
REFRESH_SCHEDULER = (_SRC / "refresh_scheduler.py").read_text(encoding="utf-8")
REFRESH_CHROMIUM = (_SRC / "refresh_chromium.py").read_text(encoding="utf-8")


def test_refresh_scheduler_uses_container_safe_headless_mode():
    # Full Chromium in the container fails to bind the CDP port under the legacy
    # "--headless" flag ("Cannot assign requested address"). The known-good v8
    # behaviour uses the new headless implementation plus a software-rasterizer
    # opt-out, so both must be present and the legacy flag must be gone.
    assert '"--headless=new",' in REFRESH_SCHEDULER
    assert '"--headless",' not in REFRESH_SCHEDULER
    assert '"--disable-software-rasterizer",' in REFRESH_SCHEDULER


def test_refresh_scheduler_prefers_full_chromium_browser_binary():
    # The headless-shell build cannot complete the Microsoft SSO redirect chain,
    # so the Linux refresh flow must prefer the full Chromium binary (matches the
    # known-good behaviour) and never fall back to chromium-headless-shell.
    # Path resolution lives in refresh_chromium.py (re-exported by scheduler).
    assert 'os.environ.get("CHROME_BIN")' in REFRESH_CHROMIUM
    assert 'shutil.which("chromium-headless-shell")' not in REFRESH_CHROMIUM
    linux_block = REFRESH_CHROMIUM[REFRESH_CHROMIUM.index("# Linux (container default)") :]
    assert linux_block.index('shutil.which("chromium")') < linux_block.index(
        'shutil.which("chromium-browser")'
    )
