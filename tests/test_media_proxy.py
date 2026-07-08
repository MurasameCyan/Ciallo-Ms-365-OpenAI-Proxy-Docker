from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy import normalize_m365_media_text
from m365_copilot_openai_proxy.refresh_scheduler import UpstreamMediaNotFound
from m365_copilot_openai_proxy.routes_media_proxy import make_signed_media_proxy_url, rewrite_m365_media_urls


SOURCE_IMAGE_URL = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fgenerated.png&fileToken=abc"
SOURCE_AUDIO_URL = "https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d6-7546f952f230bb9dd3cd0c17061b0ed3/views/original/bird_chirp.wav"


def _asyncgw_url(filename: str) -> str:
    return f"https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d6-7546f952f230bb9dd3cd0c17061b0ed3/views/original/{filename}"


class FakeRefreshScheduler:
    def __init__(self, content: bytes = b"png-bytes", content_type: str = "image/png"):
        self.calls: list[tuple[str, str]] = []
        self.content = content
        self.content_type = content_type

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        return True

    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        self.calls.append((account_id, url))
        return self.content, self.content_type


class FakeNotFoundRefreshScheduler(FakeRefreshScheduler):
    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        self.calls.append((account_id, url))
        raise UpstreamMediaNotFound("upstream media returned HTTP 404")


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


def test_normalize_m365_media_text_converts_raw_proxy_image_url_to_markdown():
    proxy_url = "http://multi.qovop.cyou/v1/m365-media?account_id=acct_1&u=abc&exp=123&sig=abc"

    assert normalize_m365_media_text(f"! `{proxy_url}` ") == f"![image]({proxy_url})"


def test_rewrite_m365_media_urls_replaces_designer_url_with_signed_proxy_url():
    rewritten = rewrite_m365_media_urls(
        f"![image]({SOURCE_IMAGE_URL})",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )

    assert rewritten.startswith("![image](http://proxy.example/v1/m365-media?")
    assert "designerapp.officeapps.live.com" not in rewritten
    assert "acct_1" in rewritten


def test_rewrite_m365_media_urls_replaces_asyncgw_audio_url_with_signed_proxy_url():
    rewritten = rewrite_m365_media_urls(
        f"已生成音频：\n\n `{SOURCE_AUDIO_URL}` ",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )

    assert rewritten.startswith("已生成音频：")
    assert "[下载 bird_chirp.wav](http://proxy.example/v1/m365-media?" in rewritten
    assert SOURCE_AUDIO_URL not in rewritten


def test_rewrite_m365_media_urls_replaces_plain_markdown_asyncgw_audio_link():
    rewritten = rewrite_m365_media_urls(
        f"已为你生成火焰燃烧效果音：[下载火焰声音 WAV 文件]({SOURCE_AUDIO_URL})",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )

    assert "[下载火焰声音 WAV 文件](http://proxy.example/v1/m365-media?" in rewritten
    assert SOURCE_AUDIO_URL not in rewritten


def test_rewrite_m365_media_urls_replaces_plain_asyncgw_audio_url():
    rewritten = rewrite_m365_media_urls(
        f"下载火焰声音 WAV 文件：{SOURCE_AUDIO_URL}",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )

    assert "下载火焰声音 WAV 文件：http://proxy.example/v1/m365-media?" in rewritten
    assert SOURCE_AUDIO_URL not in rewritten


def test_media_proxy_route_returns_bytes_for_valid_signed_designer_url(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Image Account", token="", token_source="cdp")
    app.state.media_proxy_secret = "secret"
    app.state.refresh_scheduler = FakeRefreshScheduler()
    client = TestClient(app)
    signed_url = make_signed_media_proxy_url(
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
    assert response.headers["x-media-proxy-trace"].startswith("med_")
    assert app.state.refresh_scheduler.calls == [(account.id, SOURCE_IMAGE_URL)]
    phases = [event["phase"] for event in app.state.media_proxy_events]
    assert phases == ["request", "fetch_start", "ok"]
    fetch_start = app.state.media_proxy_events[1]
    assert fetch_start["source_query_keys"] == ["fileToken", "path"]
    assert fetch_start["has_file_token"] is True
    assert fetch_start["has_path"] is True


def test_media_proxy_default_timeout_allows_chromium_fallback_window(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))

    assert app.state.media_proxy_timeout >= 55.0


def test_media_proxy_route_times_out_slow_fetcher(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Image Account", token="", token_source="cdp")
    app.state.media_proxy_secret = "secret"
    app.state.media_proxy_timeout = 0.01
    app.state.refresh_scheduler = SlowRefreshScheduler()
    client = TestClient(app)
    signed_url = make_signed_media_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_IMAGE_URL,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 504
    assert app.state.media_proxy_events[-1]["phase"] == "timeout"
    assert app.state.media_proxy_events[-1]["trace_id"].startswith("med_")


def test_media_proxy_route_rejects_unsigned_request(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    client = TestClient(app)

    response = client.get(f"/v1/m365-media?u={SOURCE_IMAGE_URL}&account_id=acct_1&exp=4102444800&sig=bad")

    assert response.status_code == 403
    event = app.state.media_proxy_events[-1]
    assert event["phase"] == "invalid_signature"
    assert event["exp"] == "4102444800"
    assert event["now"] > 0
    assert event["expired"] is False


def test_m365_media_default_suffixes_cover_common_media_and_programming_files():
    allowed = [
        "generated.png",
        "photo.webp",
        "clip.mkv",
        "song.wav",
        "slides.pptx",
        "table.xlsx",
        "archive.7z",
        "main.py",
        "component.tsx",
        "Dockerfile",
    ]

    for filename in allowed:
        rewritten = rewrite_m365_media_urls(
            f"文件： `{_asyncgw_url(filename)}`",
            base_url="http://proxy.example",
            account_id="acct_1",
            secret="secret",
            now=1000,
        )
        assert f"[下载 {filename}](http://proxy.example/v1/m365-media?" in rewritten


def test_m365_media_runtime_suffixes_can_allow_custom_extensions():
    custom_url = _asyncgw_url("model.glb")

    assert custom_url in rewrite_m365_media_urls(
        f"文件： `{custom_url}`",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
    )
    rewritten = rewrite_m365_media_urls(
        f"文件： `{custom_url}`",
        base_url="http://proxy.example",
        account_id="acct_1",
        secret="secret",
        now=1000,
        allowed_suffixes=["glb"],
    )

    assert "[下载 model.glb](http://proxy.example/v1/m365-media?" in rewritten
    assert custom_url not in rewritten


def test_media_proxy_route_returns_audio_bytes_for_valid_signed_asyncgw_url(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Audio Account", token="", token_source="cdp")
    app.state.media_proxy_secret = "secret"
    app.state.refresh_scheduler = FakeRefreshScheduler(content=b"wav-bytes", content_type="audio/wav")
    client = TestClient(app)
    signed_url = make_signed_media_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_AUDIO_URL,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 200
    assert response.content == b"wav-bytes"
    assert response.headers["content-type"] == "audio/wav"
    assert app.state.refresh_scheduler.calls == [(account.id, SOURCE_AUDIO_URL)]


def test_media_proxy_route_returns_404_for_upstream_media_not_found(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Missing Media Account", token="", token_source="cdp")
    app.state.media_proxy_secret = "secret"
    app.state.refresh_scheduler = FakeNotFoundRefreshScheduler()
    client = TestClient(app)
    signed_url = make_signed_media_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_AUDIO_URL,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Media not found"
    assert app.state.refresh_scheduler.calls == [(account.id, SOURCE_AUDIO_URL)]


def test_media_proxy_route_uses_runtime_suffixes_for_custom_media(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    account = app.state.account_store.add(name="Media Account", token="", token_source="cdp")
    app.state.media_proxy_secret = "secret"
    app.state.runtime_settings["media_proxy_suffixes"] = ["glb"]
    app.state.refresh_scheduler = FakeRefreshScheduler(content=b"glb-bytes", content_type="model/gltf-binary")
    client = TestClient(app)
    source_url = _asyncgw_url("model.glb")
    signed_url = make_signed_media_proxy_url(
        "http://testserver",
        account.id,
        source_url,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 200
    assert response.content == b"glb-bytes"
    assert app.state.refresh_scheduler.calls == [(account.id, source_url)]


def test_media_proxy_route_rejects_non_designer_hosts(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass"))
    app.state.media_proxy_secret = "secret"
    client = TestClient(app)
    signed_url = make_signed_media_proxy_url(
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
    app.state.media_proxy_secret = "secret"
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

