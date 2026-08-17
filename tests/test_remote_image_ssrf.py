"""The image URL in a chat request is caller-controlled, so downloading it is a
trust boundary: only http(s) to a publicly routable address, and the refusal has
to happen *before* the request goes out -- a blocked request that is still sent
has already probed the network, whatever we do with the response.

SSRF rule reference: HEXUXIU/M365-Copilot2API (MIT), internal/chathub/ssrf.go.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from m365_copilot_openai_proxy import substrate_upload


class _NoRequestClient:
    """Stand-in for httpx.AsyncClient that fails if anything is fetched."""

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> "_NoRequestClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def get(self, url):  # noqa: ANN001
        raise AssertionError(f"a blocked URL was fetched anyway: {url}")


class _Response:
    def __init__(self, status_code: int = 200, headers: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


class _ScriptedClient:
    """Serves one queued response per GET and records the URLs it was asked for."""

    responses: list[_Response] = []
    requested: list[str] = []

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> "_ScriptedClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def get(self, url):  # noqa: ANN001
        _ScriptedClient.requested.append(str(url))
        return _ScriptedClient.responses.pop(0)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",  # cloud metadata
        "http://127.0.0.1:12881/admin",  # our own admin port
        "http://[::1]/x.png",
        "https://10.0.0.5/x.png",
        "https://192.168.1.1/x.png",
        "https://172.16.9.9/x.png",
        "https://100.64.0.1/x.png",  # CGNAT
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/",
        "https:///x.png",  # no host at all
    ],
)
def test_non_public_targets_are_refused_without_a_request(monkeypatch, url):
    monkeypatch.setattr(httpx, "AsyncClient", _NoRequestClient)
    assert asyncio.run(substrate_upload._fetch_remote_image(url)) is None


def test_a_public_image_url_still_downloads(monkeypatch):
    _ScriptedClient.responses = [
        _Response(200, {"content-type": "image/png"}, b"\x89PNG-bytes"),
    ]
    _ScriptedClient.requested = []
    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)

    fetched = asyncio.run(substrate_upload._fetch_remote_image("https://93.184.216.34/logo.png"))

    assert fetched is not None
    b64, media_type = fetched
    assert media_type == "image/png"
    assert b64 == "iVBORy1ieXRlcw=="
    assert _ScriptedClient.requested == ["https://93.184.216.34/logo.png"]


def test_a_redirect_onto_an_internal_address_is_not_followed(monkeypatch):
    # A public URL that 302s to localhost is the SSRF that survives a naive
    # "validate the URL the client gave us" check, so each hop is re-validated.
    _ScriptedClient.responses = [
        _Response(302, {"location": "http://127.0.0.1:12881/admin"}),
        _Response(200, {"content-type": "image/png"}, b"leaked"),
    ]
    _ScriptedClient.requested = []
    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)

    assert asyncio.run(substrate_upload._fetch_remote_image("https://93.184.216.34/logo.png")) is None
    assert _ScriptedClient.requested == ["https://93.184.216.34/logo.png"]


def test_a_redirect_chain_that_stays_public_is_followed(monkeypatch):
    _ScriptedClient.responses = [
        _Response(302, {"location": "/real.png"}),
        _Response(200, {"content-type": "image/jpeg"}, b"jpeg-bytes"),
    ]
    _ScriptedClient.requested = []
    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)

    fetched = asyncio.run(substrate_upload._fetch_remote_image("https://93.184.216.34/logo.png"))

    assert fetched is not None and fetched[1] == "image/jpeg"
    assert _ScriptedClient.requested == [
        "https://93.184.216.34/logo.png",
        "https://93.184.216.34/real.png",
    ]


def test_a_redirect_loop_gives_up_instead_of_spinning(monkeypatch):
    _ScriptedClient.responses = [_Response(302, {"location": "/next.png"}) for _ in range(10)]
    _ScriptedClient.requested = []
    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)

    assert asyncio.run(substrate_upload._fetch_remote_image("https://93.184.216.34/logo.png")) is None
    assert len(_ScriptedClient.requested) <= substrate_upload._MAX_REDIRECT_HOPS + 1
