from __future__ import annotations

from pathlib import Path


REFRESH_SCHEDULER = (Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy" / "refresh_scheduler.py").read_text(encoding="utf-8")


def test_refresh_scheduler_uses_container_safe_headless_mode():
    assert '"--headless",' in REFRESH_SCHEDULER
    assert '"--headless=new",' not in REFRESH_SCHEDULER
    assert '"--disable-software-rasterizer",' not in REFRESH_SCHEDULER


def test_refresh_scheduler_prefers_configured_or_headless_shell_browser_binary():
    assert 'os.environ.get("CHROME_BIN")' in REFRESH_SCHEDULER
    assert 'shutil.which("chromium-headless-shell")' in REFRESH_SCHEDULER
    linux_block = REFRESH_SCHEDULER[REFRESH_SCHEDULER.index('# Linux (container default)'):]
    assert linux_block.index('shutil.which("chromium-headless-shell")') < linux_block.index('shutil.which("chromium")')
