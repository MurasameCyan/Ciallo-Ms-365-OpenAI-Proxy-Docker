from __future__ import annotations

from pathlib import Path


REFRESH_SCHEDULER = (Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy" / "refresh_scheduler.py").read_text(encoding="utf-8")


def test_refresh_scheduler_uses_container_safe_headless_mode():
    assert '"--headless",' in REFRESH_SCHEDULER
    assert '"--headless=new",' not in REFRESH_SCHEDULER
    assert '"--disable-software-rasterizer",' not in REFRESH_SCHEDULER


def test_refresh_scheduler_prefers_full_chromium_browser_binary():
    # The headless-shell build cannot complete the Microsoft SSO redirect chain,
    # so the Linux refresh flow must prefer the full Chromium binary (matches the
    # known-good behaviour) and never fall back to chromium-headless-shell.
    assert 'os.environ.get("CHROME_BIN")' in REFRESH_SCHEDULER
    assert 'shutil.which("chromium-headless-shell")' not in REFRESH_SCHEDULER
    linux_block = REFRESH_SCHEDULER[REFRESH_SCHEDULER.index('# Linux (container default)'):]
    assert linux_block.index('shutil.which("chromium")') < linux_block.index('shutil.which("chromium-browser")')
