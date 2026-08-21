from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.substrate_client import (
    SubstrateCopilotError,
    SubstrateThrottled,
)
from m365_copilot_openai_proxy.tone_options import TONE_OPTIONS
from m365_copilot_openai_proxy.routes_api_images import (
    _image_url_from_text,
    _safe_image_record_text,
)


SOURCE_IMAGE_URL = (
    "https://designerapp.officeapps.live.com/designerapp/document.ashx"
    "?path=%2Fgenerated.png&fileToken=abc"
)


class FakeImageClient:
    def __init__(self):
        self._tone = "Magic"

    async def chat(self, prompt, additional_context, session=None, images=None):
        assert "orange cat" in prompt
        assert "1024x1024" in prompt
        assert self._tone == "Gpt_5_6_Reasoning"
        return f"![generated image]({SOURCE_IMAGE_URL})"


def _client(tmp_path):
    first = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = first.state.account_store.add(
        name="Image Account", token="account-token", token_source="manual"
    )
    key = first.state.key_store.add(name="Image Key", account_id=account.id)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: FakeImageClient(),
    )
    app.state.tone_options = TONE_OPTIONS
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client


def test_images_generations_returns_signed_proxy_url(tmp_path):
    client = _client(tmp_path)
    response = client.post(
        "/v1/images/generations",
        json={
            "model": "gpt-5.6",
            "prompt": "orange cat",
            "n": 1,
            "size": "1024x1024",
            "response_format": "url",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["created"], int)
    assert body["data"][0]["url"].startswith(
        "http://testserver/v1/m365-media?"
    )
    assert body["data"][0]["revised_prompt"] == "orange cat"
    assert "fileToken" not in client.app.state.call_log[-1].get("response_text", "")
    assert SOURCE_IMAGE_URL not in client.app.state.call_log[-1].get("response_text", "")


def test_images_generations_rejects_unsupported_batch_and_format(tmp_path):
    client = _client(tmp_path)
    batch = client.post(
        "/v1/images/generations",
        json={"model": "m365-copilot", "prompt": "cat", "n": 2},
    )
    encoded = client.post(
        "/v1/images/generations",
        json={
            "model": "m365-copilot",
            "prompt": "cat",
            "response_format": "b64_json",
        },
    )
    unverified_size = client.post(
        "/v1/images/generations",
        json={"model": "m365-copilot", "prompt": "cat", "size": "512x512"},
    )

    assert batch.status_code == 400
    assert encoded.status_code == 400
    assert unverified_size.status_code == 400


def test_images_generations_rejects_non_integer_n_without_500(tmp_path):
    response = _client(tmp_path).post(
        "/v1/images/generations",
        json={"model": "gpt-5.6", "prompt": "cat", "n": "many"},
    )

    assert response.status_code == 400
    error = response.json()
    assert "n" in (error.get("detail") or error.get("error", {}).get("message", ""))


def test_images_generations_rejects_invalid_json_without_500(tmp_path):
    response = _client(tmp_path).post(
        "/v1/images/generations",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400


def test_images_generations_records_estimated_input_usage(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/v1/images/generations",
        json={"model": "gpt-5.6", "prompt": "orange cat", "size": "1024x1024"},
    )

    assert response.status_code == 200
    stats = client.app.state.usage_store.summary()
    assert stats["calls_total"] == 1
    assert stats["input_tokens"] > 0


def test_images_generations_fails_when_upstream_returns_no_image(tmp_path):
    class NoImageClient:
        async def chat(self, prompt, additional_context, session=None, images=None):
            return "I could not generate an image."

    first = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = first.state.account_store.add(name="A", token="account-token")
    key = first.state.key_store.add(name="K", account_id=account.id)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: NoImageClient(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/images/generations",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "m365-copilot", "prompt": "cat"},
    )

    assert response.status_code == 502
    assert client.app.state.usage_store.summary()["calls_total"] == 1
    assert client.app.state.call_log[-1]["error"] == "no_generated_image"


def test_image_url_parser_strips_markdown_backtick():
    assert _image_url_from_text(f"Here `{SOURCE_IMAGE_URL}`") == SOURCE_IMAGE_URL


def test_image_record_redacts_a_whole_file_token_that_contains_an_s():
    # The fallback runs on hosts the URL pattern does not match, and a real
    # fileToken is base64-ish, so it usually does contain an "s".
    safe = _safe_image_record_text("see https://other.example/get?fileToken=ab-s3cret then")
    assert "s3cret" not in safe
    assert "fileToken=[redacted]" in safe


@pytest.mark.parametrize("rewrite_error", [False, True])
def test_images_generations_never_returns_unsecured_upstream_url(
    tmp_path, monkeypatch, rewrite_error
):
    client = _client(tmp_path)

    if rewrite_error:
        def broken_rewriter(app, request):
            def rewrite(text):
                raise OSError("rewrite failed")

            return rewrite

        monkeypatch.setattr(
            "m365_copilot_openai_proxy.routes_api_images.request_media_rewriter",
            broken_rewriter,
        )
    else:
        monkeypatch.setattr(
            "m365_copilot_openai_proxy.routes_api_images.request_media_rewriter",
            lambda app, request: lambda text: text,
        )

    response = client.post(
        "/v1/images/generations",
        json={"model": "gpt-5.6", "prompt": "orange cat"},
    )

    assert response.status_code == 502
    assert SOURCE_IMAGE_URL not in response.text
    assert "fileToken" not in response.text
    assert SOURCE_IMAGE_URL not in client.app.state.call_log[-1].get("response_text", "")
    assert "fileToken" not in client.app.state.call_log[-1].get("response_text", "")
    assert client.app.state.usage_store.summary()["calls_total"] == 1
    expected_error = "media_rewrite_failed" if rewrite_error else "unsecured_generated_image_url"
    assert client.app.state.call_log[-1]["error"] == expected_error


def test_images_generations_maps_upstream_throttle_to_429(tmp_path):
    class ThrottledImageClient:
        _tone = "Magic"

        async def chat(self, prompt, additional_context, session=None, images=None):
            raise SubstrateThrottled("upstream result: Throttled")

    first = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = first.state.account_store.add(name="A", token="account-token")
    key = first.state.key_store.add(name="K", account_id=account.id)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: ThrottledImageClient(),
    )
    app.state.tone_options = TONE_OPTIONS

    response = TestClient(app).post(
        "/v1/images/generations",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "gpt-5.6", "prompt": "cat"},
    )

    assert response.status_code == 429


def test_images_generations_maps_other_upstream_errors_to_502(tmp_path):
    class BrokenImageClient:
        _tone = "Magic"

        async def chat(self, prompt, additional_context, session=None, images=None):
            raise SubstrateCopilotError("socket closed")

    first = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = first.state.account_store.add(name="A", token="account-token")
    key = first.state.key_store.add(name="K", account_id=account.id)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: BrokenImageClient(),
    )
    app.state.tone_options = TONE_OPTIONS

    response = TestClient(app).post(
        "/v1/images/generations",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "gpt-5.6", "prompt": "cat"},
    )

    assert response.status_code == 502
