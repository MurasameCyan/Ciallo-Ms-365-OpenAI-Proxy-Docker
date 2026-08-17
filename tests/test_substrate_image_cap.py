"""The per-turn image ceiling (docs/audit-2026-08-18-vs-hexuxiu.md, 待办 1).

The image list comes straight from the client, and each entry costs a serial
upload -- a remote one costs a download of up to 20 MiB plus base64 on top. An
uncapped list turns one request into an arbitrarily long fetch loop, so the cap
is pinned here along with the log line that keeps the truncation from being
silent.
"""
from __future__ import annotations

import asyncio
import logging

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import (
    _MAX_IMAGES_PER_TURN,
    SubstrateCopilotClient,
)


def _client() -> SubstrateCopilotClient:
    client = object.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._oid = "oid"
    client._tid = "tid"
    return client


def _upload(images, monkeypatch) -> list[dict]:
    seen: list = []

    async def _fake_upload(token, oid, tid, conversation_id, image):
        seen.append(image)
        return {"docId": f"doc-{len(seen)}"}

    monkeypatch.setattr(substrate_client, "upload_image", _fake_upload, raising=False)
    import m365_copilot_openai_proxy.substrate_upload as upload_module

    monkeypatch.setattr(upload_module, "upload_image", _fake_upload)
    annotations = asyncio.run(_client()._upload_images(images))
    return seen, annotations


def test_a_turn_beyond_the_cap_uploads_only_the_cap(monkeypatch, caplog):
    images = [f"image-{i}" for i in range(_MAX_IMAGES_PER_TURN + 5)]

    with caplog.at_level(logging.WARNING):
        seen, annotations = _upload(images, monkeypatch)

    assert seen == images[:_MAX_IMAGES_PER_TURN]
    assert len(annotations) == _MAX_IMAGES_PER_TURN
    # A silent cap reads as "the model saw everything" when it did not.
    assert any("dropping the rest" in r.getMessage() for r in caplog.records)


def test_a_turn_within_the_cap_is_untouched(monkeypatch, caplog):
    images = [f"image-{i}" for i in range(_MAX_IMAGES_PER_TURN)]

    with caplog.at_level(logging.WARNING):
        seen, annotations = _upload(images, monkeypatch)

    assert seen == images
    assert len(annotations) == _MAX_IMAGES_PER_TURN
    assert not caplog.records


def test_no_images_uploads_nothing(monkeypatch):
    assert _upload([], monkeypatch) == ([], [])
    assert _upload(None, monkeypatch) == ([], [])
