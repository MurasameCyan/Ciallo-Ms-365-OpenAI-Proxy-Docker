from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.image_proxy import normalize_m365_image_text
from m365_copilot_openai_proxy.routes_image_proxy import make_signed_image_proxy_url, rewrite_m365_image_urls


SOURCE_IMAGE_URL = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fgenerated.png&fileToken=abc"


class FakeRefreshScheduler:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        return True

    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        self.calls.append((account_id, url))
        return b"png-bytes", "image/png"


class FakeCopilotClient:
    async def chat_stream(self, prompt, additional_context, session=None):
        yield f"![image]({SOURCE_IMAGE_URL})"

    async def chat(self, prompt, additional_context, session=None):
        return f"![image]({SOURCE_IMAGE_URL})"


class SlowRefreshScheduler:
    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        await asyncio.sleep(0.05)
        return b"late", "image/png"


def _path_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + "?" + parsed.query


def test_normalize_m365_image_text_converts_raw_proxy_image_url_to_markdown():
    proxy_url = "http://multi.qovop.cyou/v1/m365-media?account_id=acct_1&u=abc&exp=123&sig=abc"

    assert normalize_m365_image_text(f"! `{proxy_url}` ") == f"![image]({proxy_url})"


def test_rewrite_m365_image_urls_replaces_designer_url_with_signed_proxy_url():
    rewritten = rewrite_m365_image_urls(
        f"![image]({SOURCE_IMAGE_URL})",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )

    assert rewritten.startswith("![image](http://proxy.example/v1/m365-media?")
    assert "designerapp.officeapps.live.com" not in rewritten
    assert "acct_1" in rewritten


def test_image_proxy_route_returns_bytes_for_valid_signed_designer_url(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Image Account", token="", token_source="cdp")
    app.state.image_proxy_secret = "secret"
    app.state.refresh_scheduler = FakeRefreshScheduler()
    client = TestClient(app)
    signed_url = make_signed_image_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_IMAGE_URL,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-image-proxy-trace"].startswith("img_")
    assert app.state.refresh_scheduler.calls == [(account.id, SOURCE_IMAGE_URL)]
    phases = [event["phase"] for event in app.state.image_proxy_events]
    assert phases == ["request", "fetch_start", "ok"]
    fetch_start = app.state.image_proxy_events[1]
    assert fetch_start["source_query_keys"] == ["fileToken", "path"]
    assert fetch_start["has_file_token"] is True
    assert fetch_start["has_path"] is True


def test_image_proxy_default_timeout_allows_chromium_fallback_window(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))

    assert app.state.image_proxy_timeout >= 55.0


def test_image_proxy_route_times_out_slow_fetcher(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Image Account", token="", token_source="cdp")
    app.state.image_proxy_secret = "secret"
    app.state.image_proxy_timeout = 0.01
    app.state.refresh_scheduler = SlowRefreshScheduler()
    client = TestClient(app)
    signed_url = make_signed_image_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_IMAGE_URL,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 504
    assert app.state.image_proxy_events[-1]["phase"] == "timeout"
    assert app.state.image_proxy_events[-1]["trace_id"].startswith("img_")


def test_image_proxy_route_rejects_unsigned_request(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    client = TestClient(app)

    response = client.get(f"/v1/m365-media?u={SOURCE_IMAGE_URL}&account_id=acct_1&exp=4102444800&sig=bad")

    assert response.status_code == 403
    event = app.state.image_proxy_events[-1]
    assert event["phase"] == "invalid_signature"
    assert event["exp"] == "4102444800"
    assert event["now"] > 0
    assert event["expired"] is False


def test_image_proxy_route_rejects_non_designer_hosts(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    app.state.image_proxy_secret = "secret"
    client = TestClient(app)
    signed_url = make_signed_image_proxy_url(
        "http://testserver",
        "acct_1",
        "https://evil.example/image.png",
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 400


def test_chat_stream_rewrites_m365_image_markdown_to_proxy_url(tmp_path):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"),
        copilot_client_factory=lambda **kwargs: FakeCopilotClient(),
    )
    account = app.state.account_store.add(name="Image Account", token="", token_source="manual")
    key = app.state.key_store.add(name="Image Key", account_id=account.id)
    app.state.image_proxy_secret = "secret"
    app.state.refresh_scheduler = FakeRefreshScheduler()
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "m365-copilot", "stream": True, "messages": [{"role": "user", "content": "生成图片"}]},
    )

    assert response.status_code == 200
    assert "/v1/m365-media?" in response.text
    assert "designerapp.officeapps.live.com" not in response.text
