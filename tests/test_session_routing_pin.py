from __future__ import annotations

import asyncio
import json
import time

import pytest

from jwe_helpers import b64url, make_jwe
from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotClient

ROUTING_HEADER = "X-RoutingParameter-SessionKey"


def _enterprise_jwt() -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "oid": "11111111-1111-4111-8111-111111111111",
        "tid": "22222222-2222-4222-8222-222222222222",
        "exp": time.time() + 3600,
    }
    return b64url(b'{"alg":"HS256"}') + "." + b64url(json.dumps(claims).encode()) + ".fixture"


class _Stop(Exception):
    pass


def _handshake_headers(monkeypatch, token: str, pin: bool | None) -> dict:
    captured: dict = {}

    def fake_connect(url, **kwargs):
        captured.update(kwargs["additional_headers"])
        raise _Stop

    monkeypatch.setattr(substrate_client.websockets, "connect", fake_connect)
    client = SubstrateCopilotClient(token)
    if pin is not None:
        client._session_routing_pin = pin

    async def connect():
        async with client._connect_for_turn("conv-1", "session-1", "request-1"):
            pass

    with pytest.raises(_Stop):
        asyncio.run(connect())
    return captured


@pytest.mark.parametrize(("token_kind", "pin", "expected"), [
    ("enterprise", None, None),
    ("enterprise", False, None),
    ("enterprise", True, "conv-1"),
    ("personal", True, None),
])
def test_routing_key_is_sent_only_when_enabled_for_enterprise(monkeypatch, token_kind, pin, expected):
    token = _enterprise_jwt() if token_kind == "enterprise" else make_jwe()

    headers = _handshake_headers(monkeypatch, token, pin)

    assert headers.get(ROUTING_HEADER) == expected
