"""Consumer turns carry images: upload, frame shape, and what happens on failure.

The bridge used to drop inbound images, so every consumer model answered blind
while Copilot's own web UI read pictures fine. These tests pin the shape measured
against the live account on 2026-09-04 (.probe/consumer_attachment_*.py), because
each part of it is something a plausible implementation gets wrong:

  * the upload needs the Bearer token -- cookies alone are HTTP 403;
  * the returned url is site-relative and goes into the frame verbatim;
  * `content-type` is an allow-list, so an unrecognised type must never be sent
    as `application/octet-stream` (400 `unsupported-content-type`);
  * an image-only turn must omit the text part rather than send an empty one,
    which upstream answers with `{"errorCode":"empty-text"}` and a dead socket.
"""

import asyncio
import base64
import json

import pytest

from m365_copilot_openai_proxy.consumer_client import (
    ClearanceRequired,
    ConsumerCopilotClient,
    ConsumerCopilotError,
    image_content_type,
)
from m365_copilot_openai_proxy.models import ImageData

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
_WEBP = b"RIFF" + b"\x1a\x00\x00\x00" + b"WEBP" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 24
_BMP = b"BM" + b"\x00" * 24


def _image(data: bytes, media_type: str = "image/png") -> ImageData:
    return ImageData(
        base64=base64.b64encode(data).decode(), media_type=media_type,
        file_name="upload-0.png",
    )


class _Response:
    def __init__(self, status_code=200, text='{"id":"conversation-1"}'):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class _FakeSocket:
    def __init__(self):
        self.sent = []
        self.frames = [
            b'{"event":"connected"}',
            b'{"event":"appendText","text":"SEEN"}{"event":"done"}',
        ]

    async def send(self, payload, flags=None):
        self.sent.append(json.loads(payload))

    async def recv(self, *, timeout=None):
        return self.frames.pop(0), 1


class _SocketContext:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *args):
        return None


class _FakeSession:
    """Answers by URL, so the attachment post is distinguishable from create."""

    def __init__(self, uploads):
        self.socket = _FakeSocket()
        self.uploads = uploads  # shared across sessions: a re-mint gets the next
        self.attachment_posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        return _Response()

    async def post(self, url, **kwargs):
        if url.endswith("/c/api/attachments"):
            self.attachment_posts.append(kwargs)
            if self.uploads:
                return self.uploads.pop(0)
            index = len(self.attachment_posts) - 1
            return _Response(
                200,
                json.dumps({"id": f"a{index}", "url": f"/attachments/a{index}.png"}),
            )
        return _Response()

    def ws_connect(self, url, **kwargs):
        return _SocketContext(self.socket)


def _run(client, prompt="say hi", images=None):
    async def collect():
        return "".join(
            [chunk async for chunk in client.chat_stream(prompt, images=images)]
        )

    return asyncio.run(collect())


def _client(sessions, uploads=None, **kwargs):
    queue = list(uploads or [])

    def factory(**_ignored):
        session = _FakeSession(queue)
        sessions.append(session)
        return session

    kwargs.setdefault("access_token", "tok")
    return ConsumerCopilotClient(session_factory=factory, **kwargs)


# --- the sniffer ------------------------------------------------------------


@pytest.mark.parametrize(
    "data, declared, expected",
    [
        (_PNG, "image/png", "image/png"),
        (_JPEG, "image/png", "image/jpeg"),        # bytes win over the claim
        (_WEBP, "", "image/webp"),
        (_GIF, "image/gif", "image/png"),          # refused by header, relabelled
        (_BMP, "image/bmp", "image/png"),
        (b"\x00\x01\x02\x03", "image/heic", "image/png"),
        (b"%PDF-1.7", "application/pdf", ""),      # not an image: skip, not 400
        (b"", "", ""),
    ],
)
def test_content_type_is_sniffed_and_never_octet_stream(data, declared, expected):
    assert image_content_type(data, declared) == expected


def test_riff_that_is_not_webp_is_not_called_an_image():
    """A RIFF wav shares webp's first four bytes; only the form type separates
    them, and mislabelling one as an image spends a request to be refused."""
    assert image_content_type(b"RIFF" + b"\x1a\x00\x00\x00" + b"WAVE", "") == ""


# --- the frame --------------------------------------------------------------


def test_the_uploaded_url_leads_the_send_frame_and_the_text_follows():
    sessions = []
    client = _client(sessions)

    assert _run(client, images=[_image(_PNG)]) == "SEEN"

    session = sessions[0]
    assert len(session.attachment_posts) == 1
    post = session.attachment_posts[0]
    assert post["headers"]["authorization"] == "Bearer tok"
    assert post["headers"]["content-type"] == "image/png"
    assert post["data"] == _PNG
    assert session.socket.sent[-1]["content"] == [
        {"type": "image", "url": "/attachments/a0.png"},
        {"type": "text", "text": "say hi"},
    ]


def test_an_image_only_turn_sends_no_text_part_at_all():
    """An empty text part is not "no question": upstream answers `empty-text` and
    drops the socket, while an image-only frame is answered."""
    sessions = []
    client = _client(sessions)

    assert _run(client, prompt="", images=[_image(_PNG)]) == "SEEN"

    assert sessions[0].socket.sent[-1]["content"] == [
        {"type": "image", "url": "/attachments/a0.png"}
    ]


def test_the_identity_type_travels_with_the_upload():
    sessions = []
    client = _client(sessions, identity_type="MicrosoftAccount")

    _run(client, images=[_image(_PNG)])

    headers = sessions[0].attachment_posts[0]["headers"]
    assert headers["x-useridentitytype"] == "MicrosoftAccount"


def test_more_images_than_the_cap_are_dropped_loudly(caplog):
    sessions = []
    client = _client(sessions)

    with caplog.at_level("WARNING"):
        _run(client, images=[_image(_PNG) for _ in range(12)])

    assert len(sessions[0].attachment_posts) == 10
    parts = sessions[0].socket.sent[-1]["content"]
    assert sum(1 for part in parts if part["type"] == "image") == 10
    assert "dropping the rest" in caplog.text


# --- when the upload does not work ------------------------------------------


@pytest.mark.parametrize(
    "upload",
    [
        _Response(400, '{"errorCode":"unsupported-content-type"}'),
        _Response(200, '{"id":"a0","url":null}'),  # 200 is not success by itself
        _Response(200, "not json at all"),
    ],
    ids=["refused", "null-url", "unparseable"],
)
def test_a_failed_upload_still_asks_the_question(upload, caplog):
    """Skip the picture, keep the turn: from outside, a dropped image and a bad
    answer look the same, so the warning is the only way to tell them apart."""
    sessions = []
    client = _client(sessions, uploads=[upload])

    with caplog.at_level("WARNING"):
        assert _run(client, images=[_image(_PNG)]) == "SEEN"

    assert sessions[0].socket.sent[-1]["content"] == [
        {"type": "text", "text": "say hi"}
    ]
    assert "no url" in caplog.text


def test_a_failed_upload_with_nothing_left_to_say_fails_locally():
    """An image-only turn whose image did not upload has no question left. Sending
    it anyway means an empty frame upstream; better a local error than a socket
    that dies with `empty-text`."""
    sessions = []
    client = _client(sessions, uploads=[_Response(400, "nope")])

    with pytest.raises(ConsumerCopilotError, match="Nothing left to send"):
        _run(client, prompt="", images=[_image(_PNG)])

    assert not [frame for frame in sessions[0].socket.sent if frame.get("content")]


def test_an_unreadable_image_is_skipped_without_a_request(caplog):
    sessions = []
    client = _client(sessions)
    broken = ImageData(base64="!!not base64!!", media_type="image/png")

    with caplog.at_level("WARNING"):
        assert _run(client, images=[broken]) == "SEEN"

    assert sessions[0].attachment_posts == []
    assert "no usable bytes" in caplog.text


def test_a_403_on_the_upload_re_mints_and_uploads_again():
    """403 is the clearance verdict, not an image problem: the same gate that
    re-mints for conversation create has to cover the attachment post, or an
    expired token turns every picture turn into a permanent failure."""
    sessions = []
    gate_calls = []

    async def gate():
        gate_calls.append(True)
        return {"access_token": "fresh"}

    client = _client(
        sessions, uploads=[_Response(403, "clearance please")], gate=gate
    )

    assert _run(client, images=[_image(_PNG)]) == "SEEN"

    assert len(gate_calls) == 1
    assert len(sessions) == 2
    assert sessions[1].attachment_posts[0]["headers"]["authorization"] == "Bearer fresh"
    assert sessions[1].socket.sent[-1]["content"][0] == {
        "type": "image",
        "url": "/attachments/a0.png",
    }


def test_a_403_with_no_gate_surfaces_as_clearance_required():
    sessions = []
    client = _client(sessions, uploads=[_Response(403, "clearance please")])

    with pytest.raises(ClearanceRequired):
        _run(client, images=[_image(_PNG)])


def test_a_remote_url_image_is_downloaded_through_the_shared_guard(monkeypatch):
    """http(s) images arrive as a url with no bytes. Fetching them through the
    M365 helper keeps one SSRF guard, redirect cap and size cap for both
    providers instead of a second, laxer downloader here."""
    from m365_copilot_openai_proxy import substrate_upload

    asked = []

    async def fake_fetch(url):
        asked.append(url)
        return base64.b64encode(_JPEG).decode(), "image/jpeg"

    monkeypatch.setattr(substrate_upload, "_fetch_remote_image", fake_fetch)

    sessions = []
    client = _client(sessions)
    remote = ImageData(base64="", media_type="", url="https://example.com/cat.jpg")

    assert _run(client, images=[remote]) == "SEEN"

    assert asked == ["https://example.com/cat.jpg"]
    post = sessions[0].attachment_posts[0]
    assert post["headers"]["content-type"] == "image/jpeg"
    assert post["data"] == _JPEG


def test_a_remote_image_that_cannot_be_fetched_is_skipped(monkeypatch):
    from m365_copilot_openai_proxy import substrate_upload

    async def fake_fetch(url):
        return None

    monkeypatch.setattr(substrate_upload, "_fetch_remote_image", fake_fetch)

    sessions = []
    client = _client(sessions)
    remote = ImageData(base64="", media_type="", url="https://example.com/cat.jpg")

    assert _run(client, images=[remote]) == "SEEN"

    assert sessions[0].attachment_posts == []


def test_a_text_only_turn_uploads_nothing():
    sessions = []
    client = _client(sessions)

    assert _run(client) == "SEEN"

    assert sessions[0].attachment_posts == []
    assert sessions[0].socket.sent[-1]["content"] == [
        {"type": "text", "text": "say hi"}
    ]


# --- telling clients about it -----------------------------------------------


def test_the_consumer_catalogue_advertises_image_input():
    """Silence is not neutral here: a client that gates its attach button on the
    capability fields refuses to send a picture this bridge would have carried.
    Image input is decided before any mode is (it is an upload plus a content
    part), so it is uniform across the catalogue -- unlike drawing and tools."""
    from m365_copilot_openai_proxy.routes_api_common import build_consumer_models_list

    entries = build_consumer_models_list(
        [
            {"model": "copilot", "mode": "smart", "status": "stable"},
            {"model": "copilot-study", "mode": "study", "status": "experimental"},
        ],
        created=0,
        planning_mode="native",
    )

    assert len(entries) == 2
    for entry in entries:
        assert entry["capabilities"]["vision"] is True
        assert entry["architecture"]["input_modalities"] == ["text", "image"]
        assert entry["architecture"]["modality"] == "text+image->text"
