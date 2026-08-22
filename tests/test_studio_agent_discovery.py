from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.studio_agent_discovery import (
    GetGptListDiscovery,
    parse_gpt_list,
)


def _jwt() -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "exp": int(time.time()) + 3600,
        "tid": "tenant-a",
        "oid": "object-a",
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _response(payload: dict, status_code: int = 200):
    class Response:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return payload

    return Response()


class _Client:
    calls = 0
    payload = {"gptList": []}

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, *, params, headers):
        type(self).calls += 1
        return _response(type(self).payload)


class _UnauthorizedClient(_Client):
    async def get(self, url, *, params, headers):
        request = httpx.Request("GET", url)
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)


def test_parse_gpt_list_matches_name_and_returns_opaque_runtime_id():
    result = parse_gpt_list(
        {
            "gptList": [
                {
                    "name": "other",
                    "gptIdentifier": {"id": "wrong.bot.gpt.default", "source": "MOS3"},
                },
                {
                    "name": "m365-tool-agent-824ab6f6",
                    "gptId": "stale-or-different",
                    "gptIdentifier": {
                        "id": "T_title.bot.gpt.default",
                        "source": "MOS3",
                        "version": "1.0.7",
                    },
                },
            ]
        },
        "m365-tool-agent-824ab6f6",
    )

    assert result == {
        "id": "T_title.bot.gpt.default",
        "name": "m365-tool-agent-824ab6f6",
        "source": "MOS3",
        "version": "1.0.7",
    }


def test_parse_gpt_list_does_not_choose_first_or_non_mos3_agent():
    payload = {
        "gptList": [
            {
                "name": "m365-tool-agent-824ab6f6",
                "gptIdentifier": {"id": "built.in", "source": "BuiltInAgents"},
            }
        ]
    }

    assert parse_gpt_list(payload, "m365-tool-agent-824ab6f6") is None


def test_parse_gpt_list_accepts_documented_top_level_gpt_id():
    payload = {
        "gptList": [
            {
                "name": "m365-tool-agent-824ab6f6",
                "gptId": "T_title.bot.gpt.default",
            }
        ]
    }

    assert parse_gpt_list(payload, "m365-tool-agent-824ab6f6") == {
        "id": "T_title.bot.gpt.default",
        "name": "m365-tool-agent-824ab6f6",
        "source": "MOS3",
        "version": "",
    }


def test_parse_gpt_list_rejects_top_level_non_mos3_source():
    payload = {
        "gptList": [
            {
                "name": "m365-tool-agent-824ab6f6",
                "gptId": "built.in",
                "source": "BuiltInAgents",
            }
        ]
    }

    assert parse_gpt_list(payload, "m365-tool-agent-824ab6f6") is None


def test_ensure_binds_matching_agent_and_coalesces_concurrent_queries(tmp_path):
    _Client.calls = 0
    _Client.payload = {
        "gptList": [
            {
                "name": "m365-tool-agent-824ab6f6",
                "gptIdentifier": {
                    "id": "T_title.bot.gpt.default",
                    "source": "MOS3",
                    "version": "1.0.7",
                },
            }
        ]
    }
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Test", token=_jwt(), token_source="cdp")
    discovery = GetGptListDiscovery(
        store,
        desired_name="m365-tool-agent-824ab6f6",
        client_factory=_Client,
    )

    async def run_all():
        return await asyncio.gather(
            discovery.ensure(account.id),
            discovery.ensure(account.id),
            discovery.ensure(account.id),
        )

    results = asyncio.run(run_all())

    assert results == [True, True, True]
    assert _Client.calls == 1
    assert store.get(account.id).studio_agent_id == "T_title.bot.gpt.default"


def test_ensure_returns_false_without_exact_match(tmp_path):
    _Client.calls = 0
    _Client.payload = {"gptList": [{"name": "another-agent", "gptIdentifier": {"id": "x.y.gpt.default", "source": "MOS3"}}]}
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Test", token=_jwt(), token_source="cdp")
    discovery = GetGptListDiscovery(
        store,
        desired_name="m365-tool-agent-824ab6f6",
        client_factory=_Client,
    )

    assert asyncio.run(discovery.ensure(account.id)) is False
    assert store.get(account.id).studio_agent_id == ""


def test_ensure_logs_token_hint_for_unauthorized_discovery(tmp_path, caplog):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Test", token=_jwt(), token_source="cdp")
    discovery = GetGptListDiscovery(
        store,
        desired_name="m365-tool-agent-824ab6f6",
        client_factory=_UnauthorizedClient,
    )

    with caplog.at_level("INFO", logger="copilot_proxy.studio_discovery"):
        assert asyncio.run(discovery.ensure(account.id)) is False

    assert "HTTP 401" in caplog.text
    assert "audience or expiry" in caplog.text
