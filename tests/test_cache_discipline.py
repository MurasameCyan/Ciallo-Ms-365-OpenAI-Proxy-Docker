"""What a response may be stored as, and what a repeat request costs.

WHY THIS EXISTS. Every JSON body this proxy serves carries conversation content,
a session-to-conversation mapping or account data, and a 200 that declares no
expiry at all lets any cache assign its own freshness to it (RFC 9111). The
stream block declared `no-cache`, which still permits storage and only forces
revalidation -- the wrong rule for an answer that exists once. And `/v1/models`
is the one body a caller may hold, so a repeat request should cost a 304 rather
than the whole list; that only works while the body carries no per-request
volatile field.

What each test defends, and the plausible bug it would catch:
  * a JSON route with no rule of its own must refuse storage, or an intermediary
    invents a freshness lifetime for conversation content
  * an error body travels the same writers, so it inherits the refusal
  * a handler that declares its own rule (the catalogue, a signed media url)
    must keep it -- the default is a default, not a fixed header
  * two identical catalogue requests must carry the same validator; a `created`
    stamped per request would move the tag every time and defeat the cache the
    tag exists to serve
  * a revalidation must be answered with an empty 304 for every form RFC 9110
    allows (exact, weak, `*`, one of a set), and only for the tag that matches
  * media revalidation still costs the upstream fetch -- the tag cannot be known
    before the bytes are -- so the test pins that it saves the body, not the
    download
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy import make_signed_media_proxy_url


SOURCE_IMAGE_URL = (
    "https://designerapp.officeapps.live.com/designerapp/document.ashx"
    "?path=%2Fgenerated.png&fileToken=abc"
)


def _app(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))


def _path_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + "?" + parsed.query


class _FakeScheduler:
    """Only what these paths call: the request gate and the media fetch."""

    def __init__(self, content: bytes = b"png-bytes", content_type: str = "image/png"):
        self.content = content
        self.content_type = content_type
        self.calls: list[tuple[str, str]] = []

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        return True

    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        self.calls.append((account_id, url))
        return self.content, self.content_type


class _FakeCopilotClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        yield "OK"

    async def chat(self, prompt, additional_context, session=None, images=None):
        return "OK"


# --------------------------------------------------------------- default refusal

def test_json_route_refuses_storage_by_default(tmp_path):
    client = TestClient(_app(tmp_path))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_error_response_refuses_storage(tmp_path):
    """An error body travels the same writers as a success one."""
    client = TestClient(_app(tmp_path))

    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_stream_refuses_storage(tmp_path):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: _FakeCopilotClient(),
    )
    account = app.state.account_store.add(name="Stream", token="", token_source="manual")
    key = app.state.key_store.add(name="Stream Key", account_id=account.id)
    app.state.refresh_scheduler = _FakeScheduler()
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "m365-copilot", "stream": True,
              "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


# ------------------------------------------------------- the one cacheable body

def test_models_declares_its_own_rule_and_keeps_it(tmp_path):
    client = TestClient(_app(tmp_path))

    response = client.get("/v1/models", headers={"Authorization": "Bearer admin-key"})

    assert response.status_code == 200
    # `private`, not `public`: the catalogue varies by key (a per-key planning
    # mode) and by account provider, so a shared cache must not reuse one
    # caller's list for another.
    assert response.headers["cache-control"] == "private, max-age=300"
    etag = response.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"'), etag


def test_models_validator_is_stable_across_two_requests(tmp_path):
    client = TestClient(_app(tmp_path))
    headers = {"Authorization": "Bearer admin-key"}

    first = client.get("/v1/models", headers=headers)
    second = client.get("/v1/models", headers=headers)

    assert first.headers["etag"] == second.headers["etag"]
    assert first.json() == second.json()


def test_models_answers_a_revalidation_with_304(tmp_path):
    client = TestClient(_app(tmp_path))
    headers = {"Authorization": "Bearer admin-key"}
    etag = client.get("/v1/models", headers=headers).headers["etag"]

    for described, candidate in (
        ("exact", etag),
        ("weak", "W/" + etag),
        ("any", "*"),
        ("in a set", f'"other", {etag}'),
    ):
        response = client.get("/v1/models", headers={**headers, "If-None-Match": candidate})

        assert response.status_code == 304, described
        assert response.content == b"", described
        assert response.headers["etag"] == etag, described

    stale = client.get("/v1/models", headers={**headers, "If-None-Match": '"stale"'})
    assert stale.status_code == 200
    assert stale.json()["object"] == "list"


# ------------------------------------------------------------------- media body

def test_media_response_carries_a_validator_and_answers_304(tmp_path):
    """The tag saves the body on the way out, not the fetch: it cannot be known
    until the bytes are, so a revalidation still asks upstream."""
    app = _app(tmp_path)
    account = app.state.account_store.add(name="Media", token="", token_source="manual")
    scheduler = _FakeScheduler()
    app.state.refresh_scheduler = scheduler
    client = TestClient(app)
    url = make_signed_media_proxy_url(
        "http://testserver",
        account.id,
        SOURCE_IMAGE_URL,
        "admin-key",
        expires_at=4_102_444_800,
    )

    first = client.get(_path_from_url(url))

    assert first.status_code == 200
    assert first.content == b"png-bytes"
    assert first.headers["cache-control"] == "private, max-age=600"
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"'), etag

    revalidated = client.get(_path_from_url(url), headers={"If-None-Match": etag})

    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert revalidated.headers["etag"] == etag

    stale = client.get(_path_from_url(url), headers={"If-None-Match": '"stale"'})

    assert stale.status_code == 200
    assert stale.content == b"png-bytes"
    assert len(scheduler.calls) == 3
