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
    last_url: str | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        FakeAuthorizedImageClient.last_headers = dict(headers or {})
        FakeAuthorizedImageClient.last_url = str(url)
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



def test_fetch_image_skips_direct_for_designerapp_and_uses_chromium(tmp_path, monkeypatch):
    # A plain httpx GET to designerapp returns HTTP 400 (no browser context), so the
    # direct path must be skipped entirely and the request replayed via Chromium's
    # in-page fetch. The fileToken-carrying URL is handed to _fetch_image_one so the
    # token can be lifted into the FileToken header there.
    monkeypatch.setattr(httpx, "AsyncClient", FakeAuthorizedImageClient)
    store = AccountStore(Path(tmp_path) / "accounts.json")
    account = store.add(name="Image Account", token="account-token", token_source="manual")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com"}])
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []
    seen: dict = {}

    async def fallback_fetch(account_id, url, event_sink=None):
        seen["url"] = url
        return b"png", "image/png"

    scheduler._fetch_image_one = fallback_fetch

    body, content_type = asyncio.run(
        scheduler.fetch_image(
            account.id,
            "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimg.png&fileToken=eyJraWQ",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"png"
    assert content_type == "image/png"
    # Direct httpx was never invoked for designerapp.
    assert FakeAuthorizedImageClient.last_url is None or "document.ashx" not in FakeAuthorizedImageClient.last_url
    assert any(e["phase"] == "direct_skip" and e["reason"] == "designer_requires_browser_fetch" for e in events)
    assert any(e["phase"] == "chromium_fallback_start" for e in events)
    # _fetch_image_one receives the URL that STILL carries the fileToken so it can
    # lift it into the FileToken header.
    assert "fileToken=eyJraWQ" in seen["url"]


def test_chromium_designer_fetch_replays_browser_request(tmp_path, monkeypatch):
    # The browser loads designer images with a designer-scoped Authorization token
    # (raw value, NO "Bearer " prefix), the fileToken moved into a FileToken header,
    # and the fileToken stripped from the query. Chromium replays that exact fetch.
    import subprocess
    import websockets

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
    account = store.add(name="Designer Account", token="account-token", token_source="manual")
    store.set_designer_auth_token(account.id, "raw-designer-jwe-token")
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com", "path": "/"}])
    (tmp_path / "profiles" / account.id).mkdir(parents=True)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    body, content_type = asyncio.run(
        scheduler._fetch_image_one(
            account.id,
            "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimg.png&fileToken=eyJraWQ",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"png"
    assert content_type == "image/png"
    expr = fake_websockets.ws.eval_expression or ""
    # The in-page fetch replays the browser's request shape verbatim.
    assert "raw-designer-jwe-token" in expr
    assert '"FileToken": "eyJraWQ"' in expr
    # fileToken is stripped from the fetched URL (moved into the header).
    assert "fileToken=eyJraWQ" not in expr
    assert "path=%2Fimg.png" in expr
    assert any(e["phase"] == "designer_url_normalized" for e in events)
    fetch_start = next(e for e in events if e["phase"] == "chromium_fetch_start")
    assert fetch_start["token_header"] is True
    assert fetch_start["auth_source"] == "designer"
    assert any(e["phase"] == "chromium_response" and e["status_code"] == 200 for e in events)


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
    nav_response_url = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fimage.png"

    def __init__(self):
        self.messages: list[str] = []
        self.extra_headers: dict | None = None
        self.set_cookies: list[dict] = []
        self.eval_expression: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, raw):
        payload = json.loads(raw)
        msg_id = payload["id"]
        method = payload["method"]
        if method in {"Network.enable", "Page.enable", "Runtime.enable"}:
            self.messages.append(json.dumps({"id": msg_id, "result": {}}))
        elif method == "Network.setCookie":
            self.set_cookies.append(dict(payload.get("params") or {}))
            self.messages.append(json.dumps({"id": msg_id, "result": {"success": True}}))
        elif method == "Network.setExtraHTTPHeaders":
            self.extra_headers = dict((payload.get("params") or {}).get("headers") or {})
            self.messages.append(json.dumps({"id": msg_id, "result": {}}))
        elif method == "Runtime.evaluate":
            self.eval_expression = str((payload.get("params") or {}).get("expression") or "")
            self.messages.append(
                json.dumps(
                    {
                        "id": msg_id,
                        "result": {
                            "result": {
                                "value": {
                                    "ok": True,
                                    "status": self.response_status,
                                    "contentType": self.response_content_type,
                                    "body": self.response_body,
                                }
                            }
                        },
                    }
                )
            )
        elif method == "Page.navigate":
            self.messages.extend(
                [
                    json.dumps(
                        {
                            "method": "Network.responseReceived",
                            "params": {
                                "requestId": "img-req",
                                "response": {
                                    "url": self.nav_response_url,
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
    # designerapp authenticates via fileToken + cookies; no Authorization header
    # (wrong-audience substrate token) is sent, so extra headers stay unset.
    assert fake_websockets.ws.extra_headers is None
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


def test_chromium_asyncgw_fetch_uses_navigate_path(tmp_path, monkeypatch):
    # asyncgw objects are served as top-level resources; the Chromium fallback must
    # still navigate to them and read the response body (NOT the designer in-page
    # fetch path, which only applies to officeapps document.ashx).
    import subprocess
    import websockets

    FakeImageWebSocket.response_status = 200
    FakeImageWebSocket.response_content_type = "audio/wav"
    FakeImageWebSocket.response_body = "d2F2"
    FakeImageWebSocket.response_base64 = True
    FakeImageWebSocket.nav_response_url = "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/0/views/original"
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
    account.media_auth_token = "media-bearer-token"
    store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value", "domain": ".asyncgw.teams.microsoft.com", "path": "/"}])
    (tmp_path / "profiles" / account.id).mkdir(parents=True)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    events: list[dict] = []

    body, content_type = asyncio.run(
        scheduler._fetch_image_one(
            account.id,
            "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/0/views/original",
            event_sink=lambda phase, **fields: events.append({"phase": phase, **fields}),
        )
    )

    assert body == b"wav"
    assert content_type == "audio/wav"
    # The navigate path sets the media bearer as an extra header (no in-page fetch).
    assert fake_websockets.ws.eval_expression is None
    assert fake_websockets.ws.extra_headers == {"Authorization": "Bearer media-bearer-token"}
    assert any(event["phase"] == "chromium_navigate" for event in events)
    assert any(event["phase"] == "chromium_response" and event["status_code"] == 200 for event in events)
