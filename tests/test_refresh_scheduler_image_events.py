from __future__ import annotations

import asyncio
import json
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


class FakeBrowserProcess:
    def poll(self):
        return 0

    def kill(self):
        pass


class FakeTabListClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return httpx.Response(
            200,
            json=[{"type": "page", "webSocketDebuggerUrl": "ws://fake-tab"}],
        )


class FakeImageWebSocket:
    def __init__(self):
        self.messages: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, raw):
        payload = json.loads(raw)
        msg_id = payload["id"]
        method = payload["method"]
        if method in {"Network.enable", "Page.enable"}:
            self.messages.append(json.dumps({"id": msg_id, "result": {}}))
        elif method == "Page.navigate":
            self.messages.extend(
                [
                    json.dumps(
                        {
                            "method": "Network.responseReceived",
                            "params": {
                                "requestId": "img-req",
                                "response": {
                                    "url": "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimage.png",
                                    "status": 200,
                                    "mimeType": "image/png",
                                },
                            },
                        }
                    ),
                    json.dumps({"method": "Network.loadingFinished", "params": {"requestId": "img-req"}}),
                    json.dumps({"id": msg_id, "result": {}}),
                ]
            )
        elif method == "Network.getResponseBody":
            self.messages.append(json.dumps({"id": msg_id, "result": {"body": "cG5n", "base64Encoded": True}}))

    async def recv(self):
        if not self.messages:
            raise asyncio.TimeoutError()
        return self.messages.pop(0)


class FakeWebsocketsModule:
    def __init__(self):
        self.ws = FakeImageWebSocket()

    def connect(self, url):
        return self.ws


def test_chromium_image_fetch_keeps_network_events_during_navigation(tmp_path, monkeypatch):
    import subprocess
    import websockets

    monkeypatch.setattr(httpx, "AsyncClient", FakeTabListClient)
    fake_websockets = FakeWebsocketsModule()
    monkeypatch.setattr(websockets, "connect", fake_websockets.connect)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeBrowserProcess())
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._chromium_path", lambda: "chrome")
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._cleanup_profile_locks", lambda profile_dir: None)

    async def close_noop(cdp_port, proc):
        return None

    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._close_chromium_gracefully", close_noop)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Image Account", token="token", token_source="manual")
    (tmp_path / "profiles" / account.id).mkdir(parents=True)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    body, content_type = asyncio.run(
        scheduler._fetch_image_one(
            account.id,
            "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimage.png",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"png"
    assert content_type == "image/png"
    assert any(event["phase"] == "chromium_response" for event in events)
    assert any(event["phase"] == "chromium_body" for event in events)
