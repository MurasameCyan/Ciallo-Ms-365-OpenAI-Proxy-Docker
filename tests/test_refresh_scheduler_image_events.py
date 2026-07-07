from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return httpx.Response(401, headers={"content-type": "text/html"}, content=b"login")


def test_fetch_image_with_cookies_records_upstream_status_before_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    scheduler = RefreshScheduler(AccountStore(Path(tmp_path) / "accounts.json"), tmp_path / "profiles")
    events: list[dict] = []

    with pytest.raises(RuntimeError, match="HTTP 401"):
        asyncio.run(
            scheduler._fetch_image_with_cookies(
                "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimage.png",
                "MUID=value",
                event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
            )
        )

    assert events[0]["phase"] == "direct_response"
    assert events[0]["status_code"] == 401
    assert events[0]["content_type"] == "text/html"
    assert events[0]["bytes"] == len(b"login")
    assert events[0]["duration_ms"] >= 0
