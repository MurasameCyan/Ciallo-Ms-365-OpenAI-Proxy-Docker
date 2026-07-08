from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy import (
    asyncgw_object_fetch_url,
    content_disposition_for_media,
    designer_object_fetch_url,
    make_signed_media_proxy_url,
    normalize_m365_media_text,
    rewrite_m365_media_urls,
)
from m365_copilot_openai_proxy.refresh_scheduler import UpstreamMediaNotFound


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


class SplitAudioCopilotClient:
    async def chat_stream(self, prompt, additional_context, session=None):
        yield "已生成文件：\n\n `https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/"
        yield "0-ea-d4-101412848fe8be7ad7f1c4c110d1fa4f/views/original/"
        yield "cat_meow.wav` \n\n（这是一个合成的“喵”声音频，可直接下载播放。）"

    async def chat(self, prompt, additional_context, session=None):
        return "已生成文件：\n\n `https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d4-101412848fe8be7ad7f1c4c110d1fa4f/views/original/cat_meow.wav` \n\n（这是一个合成的“喵”声音频，可直接下载播放。）"


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


def test_media_proxy_route_fetches_global_token_media(monkeypatch, tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN="global-token"))
    app.state.media_proxy_secret = "secret"
    client = TestClient(app)
    source_url = _asyncgw_url("cat_meow.wav")
    seen_headers = []

    class FakeResponse:
        status_code = 200
        content = b"wav-bytes"
        headers = {"content-type": "audio/wav"}
        url = source_url

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            seen_headers.append(headers)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    signed_url = make_signed_media_proxy_url(
        "http://testserver",
        "__global__",
        source_url,
        "secret",
        expires_at=4_102_444_800,
    )

    response = client.get(_path_from_url(signed_url))

    assert response.status_code == 200
    assert response.content == b"wav-bytes"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-disposition"] == 'attachment; filename="cat_meow.wav"'
    assert seen_headers[0]["Authorization"] == "Bearer global-token"
    assert [event["phase"] for event in app.state.media_proxy_events] == ["request", "fetch_start", "asyncgw_url_normalized", "global_direct_start", "global_direct_response", "ok"]


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


def test_chat_stream_rewrites_split_asyncgw_audio_url_with_global_key(tmp_path):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN="global-token"),
        copilot_client_factory=lambda **kwargs: SplitAudioCopilotClient(),
    )
    app.state.media_proxy_secret = "secret"
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer admin-key"},
        json={"model": "m365-copilot", "stream": True, "messages": [{"role": "user", "content": "生成猫叫声"}]},
    )

    assert response.status_code == 200
    assert "/v1/m365-media?" in response.text
    assert "asyncgw.teams.microsoft.com" not in response.text
    call_record = app.state.call_log[-1]
    assert "/v1/m365-media?" in call_record["response_text"]
    assert "asyncgw.teams.microsoft.com" not in call_record["response_text"]


def test_asyncgw_object_fetch_url_strips_trailing_filename():
    # The real asyncgw object lives at .../views/original; the trailing filename
    # (e.g. bird_chirp.wav) is a model-supplied display name, not part of the
    # object path, and asyncgw returns 404 when it is present.
    assert (
        asyncgw_object_fetch_url(SOURCE_AUDIO_URL)
        == "https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d6-7546f952f230bb9dd3cd0c17061b0ed3/views/original"
    )


def test_asyncgw_object_fetch_url_keeps_bare_object_url_unchanged():
    bare = "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d9-c5a1299ea9a25ded992d45a176fd595e/views/original"
    assert asyncgw_object_fetch_url(bare) == bare


def test_asyncgw_object_fetch_url_leaves_non_asyncgw_urls_unchanged():
    assert asyncgw_object_fetch_url(SOURCE_IMAGE_URL) == SOURCE_IMAGE_URL


def test_content_disposition_for_media_uses_source_filename():
    # The model-supplied display filename (rain_sound.wav) is stripped before the
    # upstream fetch, but should still drive the browser download name.
    disposition = content_disposition_for_media(_asyncgw_url("rain_sound.wav"))
    assert disposition == 'attachment; filename="rain_sound.wav"'


def test_content_disposition_for_media_encodes_non_ascii_filename():
    disposition = content_disposition_for_media(_asyncgw_url("%E9%9B%A8%E5%A3%B0.wav"))
    # Falls back to an ASCII-safe filename and adds an RFC 5987 filename* value.
    assert disposition.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in disposition
    assert "%E9%9B%A8%E5%A3%B0.wav" in disposition


def test_designer_object_fetch_url_strips_file_token():
    # The browser loads designer images WITHOUT the fileToken query param, using a
    # designer-scoped Authorization token instead. The model-supplied fileToken has
    # the wrong audience and triggers HTTP 401, so drop it before fetching while
    # keeping every other query param (path/dcHint/speCId/speType/speIdx) intact.
    source = (
        "https://designerapp.officeapps.live.com/designerapp/document.ashx"
        "?path=%2Fgenerated.png&dcHint=JapanEast&speCId=abc&speType=Image"
        "&speIdx=0&fileToken=eyJraWQ"
    )
    result = designer_object_fetch_url(source)
    assert "fileToken=" not in result
    assert "path=%2Fgenerated.png" in result
    assert "dcHint=JapanEast" in result
    assert "speCId=abc" in result
    assert "speType=Image" in result
    assert "speIdx=0" in result


def test_designer_object_fetch_url_keeps_url_without_file_token_unchanged():
    source = (
        "https://designerapp.officeapps.live.com/designerapp/document.ashx"
        "?path=%2Fgenerated.png&dcHint=JapanEast"
    )
    assert designer_object_fetch_url(source) == source


def test_designer_object_fetch_url_leaves_non_designer_urls_unchanged():
    # asyncgw audio URLs must not be touched by the designer normalizer.
    assert designer_object_fetch_url(SOURCE_AUDIO_URL) == SOURCE_AUDIO_URL

