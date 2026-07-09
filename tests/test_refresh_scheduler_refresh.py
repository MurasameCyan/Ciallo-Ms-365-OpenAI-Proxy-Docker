from __future__ import annotations

import asyncio
from pathlib import Path

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


class FakeBrowserProcess:
    def poll(self):
        return 0

    def kill(self):
        pass


def test_refresh_one_rehydrates_profile_with_stored_cookies_before_capture(tmp_path, monkeypatch):
    calls: list[str] = []
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Cookie Account", token="expired-token", token_source="cdp")
    store.set_cookies(
        account.id,
        [{"name": "MUID", "value": "cookie-value", "domain": ".microsoft.com", "path": "/"}],
    )
    scheduler = RefreshScheduler(store, tmp_path / "profiles")

    async def inject_cookies_one(account_id, cookies):
        calls.append("inject")
        assert account_id == account.id
        assert cookies[0]["name"] == "MUID"
        return 1, 1

    def wait_for_m365_page(port, timeout):
        calls.append("wait")
        return True

    async def extract_token(port, allow_nudge=True):
        calls.append("extract")
        return "fresh-token"

    async def close_noop(port, proc):
        calls.append("close")

    monkeypatch.setattr(scheduler, "_inject_cookies_one", inject_cookies_one)
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._chromium_path", lambda: "chrome")
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._cleanup_profile_locks", lambda profile_dir: None)
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._close_chromium_gracefully", close_noop)
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler.subprocess.Popen", lambda *args, **kwargs: FakeBrowserProcess())
    monkeypatch.setattr("m365_copilot_openai_proxy.cli._wait_for_m365_page", wait_for_m365_page)
    monkeypatch.setattr("m365_copilot_openai_proxy.cli._cdp_extract_token", extract_token)
    monkeypatch.setattr("m365_copilot_openai_proxy.cli._cdp_tab_summary", lambda port: "m365 tab")

    assert asyncio.run(scheduler._refresh_one(account.id)) is True
    assert calls[:3] == ["inject", "wait", "extract"]
    assert store.get(account.id).token == "fresh-token"
