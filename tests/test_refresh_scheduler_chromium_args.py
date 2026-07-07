from __future__ import annotations

from pathlib import Path


REFRESH_SCHEDULER = (Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy" / "refresh_scheduler.py").read_text(encoding="utf-8")


def test_refresh_scheduler_uses_container_safe_headless_mode():
    assert '"--headless",' in REFRESH_SCHEDULER
    assert '"--headless=new",' not in REFRESH_SCHEDULER
    assert '"--disable-software-rasterizer",' not in REFRESH_SCHEDULER
