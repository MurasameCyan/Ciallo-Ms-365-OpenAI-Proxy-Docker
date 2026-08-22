"""Read-only discovery of the account's published Copilot Studio agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from .account_store import AccountStore, resolve_account_proxy

_log = logging.getLogger("copilot_proxy.studio_discovery")
GET_GPT_LIST_URL = "https://substrate.office.com/m365Copilot/GetGptList"
GET_GPT_LIST_VARIANTS = "feature.disabledisallowedmsgs"
GET_GPT_LIST_OPTIONS = (
    "flux_gpt_data_retriever_enterprise",
    "plugins_as_declarative_agents",
)
STUDIO_AGENT_INSTRUCTIONS = """You are the execution core of an automated agent. When the incoming message contains available tool definitions, request exactly one action by outputting ONLY this shape:
```tool_call
{"name":"<exact tool name>","arguments":{...}}
```
The fenced block is an action executed immediately by the host, not an example. Stop and wait for the real tool result before continuing. Never claim an action succeeded before its result is returned. When no tool applies, answer normally in natural language."""
DEFAULT_STUDIO_AGENT_NAME = "m365-tool-agent-" + hashlib.sha256(
    STUDIO_AGENT_INSTRUCTIONS.encode("utf-8")
).hexdigest()[:8]


def parse_gpt_list(payload: Any, desired_name: str) -> dict[str, str] | None:
    """Return an exact, published MOS3 entry without guessing its ID.

    Current ChatHub responses expose the canonical value as
    ``gptIdentifier.id``. Microsoft documentation also shows a legacy/top-level
    ``gptId`` shape, so accept that only for a precisely named declarative agent
    when the response does not explicitly classify it as another source.
    """
    if not isinstance(payload, dict) or not isinstance(desired_name, str):
        return None
    entries = payload.get("gptList")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("name") != desired_name:
            continue
        identifier = entry.get("gptIdentifier")
        if isinstance(identifier, dict):
            agent_id = identifier.get("id")
            source = identifier.get("source")
            version = identifier.get("version")
            if (
                not isinstance(agent_id, str)
                or not agent_id.strip()
                or source != "MOS3"
            ):
                continue
        else:
            # Microsoft’s handoff documentation names the public field ``gptId``.
            # Do not use it when the service explicitly says this is a non-MOS3
            # source; the exact generated name is our only stable discriminator
            # for this older response shape.
            agent_id = entry.get("gptId")
            source = entry.get("source")
            if (
                source not in (None, "", "MOS3")
                or not isinstance(agent_id, str)
                or not agent_id.strip()
            ):
                continue
            version = entry.get("version") or ""
        return {
            "id": agent_id.strip(),
            "name": desired_name,
            "source": "MOS3",
            "version": str(version or ""),
        }
    return None


class GetGptListDiscovery:
    """Per-account, coalesced read-only lookup."""

    def __init__(
        self,
        accounts: AccountStore,
        *,
        desired_name: str,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        timeout: float = 15.0,
    ) -> None:
        self._accounts = accounts
        self._desired_name = desired_name
        self._client_factory = client_factory
        self._timeout = timeout
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, account_id: str) -> asyncio.Lock:
        lock = self._locks.get(account_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[account_id] = lock
        return lock

    @staticmethod
    def eligible(account: Any) -> bool:
        """Only accounts with an unattended session should auto-discover."""
        return bool(
            getattr(account, "token", "")
            and (
                getattr(account, "token_source", "") == "cdp"
                or getattr(account, "refresh_token", "")
                or getattr(account, "cookie_valid", False)
            )
        )

    async def ensure(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if (
            account is None
            or getattr(account, "provider", "m365") != "m365"
            or not self.eligible(account)
        ):
            return False
        if getattr(account, "studio_agent_ready", False):
            return True
        async with self._lock(account_id):
            account = self._accounts.get(account_id)
            if (
                account is None
                or getattr(account, "provider", "m365") != "m365"
                or not self.eligible(account)
            ):
                return False
            if getattr(account, "studio_agent_ready", False):
                return True
            token = str(getattr(account, "token", "") or "").strip()
            if not token:
                return False
            request = {
                "optionsSets": list(GET_GPT_LIST_OPTIONS),
                "traceId": str(uuid.uuid4()),
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Scenario": "officeweb",
            }
            try:
                async with self._client_factory(
                    timeout=self._timeout,
                    proxy=resolve_account_proxy(account) or None,
                ) as client:
                    response = await client.get(
                        GET_GPT_LIST_URL,
                        params={
                            "request": json.dumps(request, separators=(",", ":")),
                            "variants": GET_GPT_LIST_VARIANTS,
                        },
                        headers=headers,
                    )
                    response.raise_for_status()
                    match = parse_gpt_list(response.json(), self._desired_name)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                hint = (
                    "; verify Substrate token audience or expiry"
                    if status == 401
                    else ""
                )
                _log.info(
                    "Studio agent discovery failed account=%s: HTTP %s%s",
                    account_id,
                    status or "error",
                    hint,
                )
                return False
            except Exception as exc:  # discovery must never block Router fallback
                _log.info("Studio agent discovery failed account=%s: %s", account_id, type(exc).__name__)
                return False
            if match is None:
                return False
            try:
                bound = self._accounts.set_studio_agent_id(account_id, match["id"])
            except (ValueError, TypeError):
                return False
            if bound is None:
                return False
            return True


async def ensure_studio_client_snapshot(app: Any, account: Any) -> tuple[str, str] | None:
    """Resolve an existing binding or discover it once before a Studio turn."""
    if account is None:
        return None
    store = getattr(app.state, "account_store", None)
    if store is None:
        return None
    snapshot = store.studio_client_snapshot(account.id)
    if snapshot is not None:
        return snapshot
    discovery = getattr(app.state, "studio_agent_discovery", None)
    if discovery is None:
        return None
    try:
        await discovery.ensure(account.id)
    except Exception:
        return None
    return store.studio_client_snapshot(account.id)
