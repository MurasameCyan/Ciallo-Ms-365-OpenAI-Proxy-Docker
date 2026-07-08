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
        return httpx.Response(401, headers={"content-type": "text/html"}, content=b"login", request=httpx.Request("GET", url))


class FakeNotFoundMediaClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return httpx.Response(404, content=b"", request=httpx.Request("GET", url))


class FakeAuthorizedImageClient:
    last_headers: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        FakeAuthorizedImageClient.last_headers = dict(headers or {})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png", request=httpx.Request("GET", url))


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
    assert events[0]["body_preview"] == "login"


def test_fetch_image_falls_back_to_chromium_after_direct_404(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeNotFoundMediaClient)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Media Account", token="account-token", token_source="manual")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".asyncgw.teams.microsoft.com"}])
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    async def fallback_fetch(account_id, url, event_sink=None):
        if event_sink:
            event_sink("chromium_body", bytes=len(b"wav-bytes"), base64_encoded=True, body_preview="")
        return b"wav-bytes", "audio/wav"

    scheduler._fetch_image_one = fallback_fetch

    body, content_type = asyncio.run(
        scheduler.fetch_image(
            account.id,
            "https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0/views/original/thunder_sound.wav",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"wav-bytes"
    assert content_type == "audio/wav"
    assert any(event["phase"] == "direct_response" and event["status_code"] == 404 for event in events)
    assert any(event["phase"] == "direct_error" and event["error_type"] == "UpstreamMediaNotFound" for event in events)
    assert any(event["phase"] == "chromium_fallback_start" for event in events)
    assert any(event["phase"] == "chromium_body" for event in events)



def test_fetch_image_with_cookies_sends_account_token_header(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAuthorizedImageClient)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Image Account", token="account-token", token_source="manual")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com"}])
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    body, content_type = asyncio.run(
        scheduler.fetch_image(
            account.id,
            "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimage.png",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"png"
    assert content_type == "image/png"
    assert FakeAuthorizedImageClient.last_headers["Authorization"] == "Bearer account-token"
    assert events[0]["phase"] == "direct_start"
    assert events[0]["token_header"] is True
    assert events[0]["auth_source"] == "account"
    assert events[0]["cookie_names"] == ["MUID"]


def test_fetch_image_with_cookies_prefers_media_auth_for_asyncgw(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAuthorizedImageClient)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Media Account", token="substrate-token", token_source="manual")
    account.media_auth_token = "media-bearer-token"
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".asyncgw.teams.microsoft.com"}])
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    body, content_type = asyncio.run(
        scheduler.fetch_image(
            account.id,
            "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/0/views/original/wave.wav",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"png"
    assert content_type == "image/png"
    assert FakeAuthorizedImageClient.last_headers["Authorization"] == "Bearer media-bearer-token"
    assert events[0]["phase"] == "asyncgw_url_normalized"
    assert events[0]["fetch_path"] == "/v1/objects/0/views/original"
    assert events[1]["phase"] == "direct_start"
    assert events[1]["token_header"] is True
    assert events[1]["auth_source"] == "media"


class FakeBrowserProcess:
    last_args: list[str] | None = None

    def __init__(self, args=None):
        FakeBrowserProcess.last_args = list(args or [])

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
    response_status = 200
    response_content_type = "image/png"
    response_body = "cG5n"
    response_base64 = True

    def __init__(self):
        self.messages: list[str] = []
        self.extra_headers: dict | None = None
        self.set_cookies: list[dict] = []

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
        elif method == "Network.setCookie":
            self.set_cookies.append(dict(payload.get("params") or {}))
            self.messages.append(json.dumps({"id": msg_id, "result": {"success": True}}))
        elif method == "Network.setExtraHTTPHeaders":
            self.extra_headers = dict((payload.get("params") or {}).get("headers") or {})
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
                                    "status": self.response_status,
                                    "mimeType": self.response_content_type,
                                },
                            },
                        }
                    ),
                    json.dumps({"method": "Network.loadingFinished", "params": {"requestId": "img-req"}}),
                    json.dumps({"id": msg_id, "result": {}}),
                ]
            )
        elif method == "Network.getResponseBody":
            self.messages.append(json.dumps({"id": msg_id, "result": {"body": self.response_body, "base64Encoded": self.response_base64}}))

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

    FakeImageWebSocket.response_status = 200
    FakeImageWebSocket.response_content_type = "image/png"
    FakeImageWebSocket.response_body = "cG5n"
    FakeImageWebSocket.response_base64 = True
    monkeypatch.setattr(httpx, "AsyncClient", FakeTabListClient)
    fake_websockets = FakeWebsocketsModule()
    monkeypatch.setattr(websockets, "connect", fake_websockets.connect)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: FakeBrowserProcess(args))
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._chromium_path", lambda: "chrome")
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._cleanup_profile_locks", lambda profile_dir: None)

    async def close_noop(cdp_port, proc):
        return None

    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._close_chromium_gracefully", close_noop)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Image Account", token="token", token_source="manual")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com", "path": "/"}])
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
    user_data_arg = next(arg for arg in FakeBrowserProcess.last_args if arg.startswith("--user-data-dir="))
    assert user_data_arg != f"--user-data-dir={tmp_path / 'profiles' / account.id}"
    assert fake_websockets.ws.extra_headers["Authorization"] == "Bearer token"
    assert any(cookie["name"] == "MUID" for cookie in fake_websockets.ws.set_cookies)
    assert any(event["phase"] == "chromium_cookies" and event["cookie_count"] == 1 for event in events)
    assert any(event["phase"] == "chromium_response" for event in events)
    assert any(event["phase"] == "chromium_body" for event in events)


def test_chromium_image_fetch_raises_not_found_for_upstream_404(tmp_path, monkeypatch):
    import subprocess
    import websockets

    FakeImageWebSocket.response_status = 404
    FakeImageWebSocket.response_content_type = "text/plain"
    FakeImageWebSocket.response_body = ""
    FakeImageWebSocket.response_base64 = False
    monkeypatch.setattr(httpx, "AsyncClient", FakeTabListClient)
    fake_websockets = FakeWebsocketsModule()
    monkeypatch.setattr(websockets, "connect", fake_websockets.connect)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: FakeBrowserProcess(args))
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._chromium_path", lambda: "chrome")
    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._cleanup_profile_locks", lambda profile_dir: None)

    async def close_noop(cdp_port, proc):
        return None

    monkeypatch.setattr("m365_copilot_openai_proxy.refresh_scheduler._close_chromium_gracefully", close_noop)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Media Account", token="token", token_source="manual")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com", "path": "/"}])
    (tmp_path / "profiles" / account.id).mkdir(parents=True)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    with pytest.raises(Exception) as exc_info:
        asyncio.run(
            scheduler._fetch_image_one(
                account.id,
                "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fmissing.wav",
                event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
            )
        )

    assert type(exc_info.value).__name__ == "UpstreamMediaNotFound"
    assert any(event["phase"] == "chromium_response" and event["status_code"] == 404 for event in events)
    assert any(event["phase"] == "chromium_body" and event["bytes"] == 0 for event in events)
