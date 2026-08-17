"""Single-model connectivity probe for one pool account.

Whether a given mode works is decided by Microsoft's rollout per account, not by
anything in this proxy: the same refresh token answers on one tone and is refused
on the next, and the only way to know is to ask. Doing that by hand meant sending
a real request through a client and reading the raw failure, so this endpoint does
exactly that one turn and reports the four outcomes an operator acts on
differently:

    ok        -- upstream answered with text; this mode works for this account
    empty     -- upstream accepted the turn and said nothing (mode not rolled out)
    refused   -- upstream declined the turn outright (mode/account not allowed)
    throttled -- quota, not availability; retry after the reported window
    error     -- transport/credential failure; nothing to conclude about the mode

The probe rides the same client factory as /v1/chat/completions -- same per-account
egress, same provider dispatch, same tone/mode resolution -- because a test that
takes a different path can pass while real traffic fails. It runs with no session,
so it starts a fresh upstream conversation and never disturbs a live one; that does
leave one short conversation behind, which the session-management view can delete.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request

from .consumer_client import AccountThrottled, ConsumerCopilotError
from .response_helpers import _json_err
from .routes_api_common import apply_request_model
from .substrate_client import (
    _EMPTY_TURN_MARKER,
    _REFUSED_TURN_MARKER,
    SubstrateCopilotError,
)

# Short enough that the answer is unambiguous, long enough that a mode which only
# emits a canned deflection still produces text we can show the operator.
_PROBE_PROMPT = "Reply with one word: pong"
_PROBE_TIMEOUT_SECONDS = 180.0
_PREVIEW_CHARS = 600


def classify_probe(reply: str, error: str = "", *, throttled: bool = False) -> str:
    """Map one probe outcome onto the verdict an operator acts on."""
    if throttled:
        return "throttled"
    if error:
        if _REFUSED_TURN_MARKER in error or _EMPTY_TURN_MARKER in error:
            return "refused"
        return "error"
    return "ok" if reply.strip() else "empty"


def _is_throttled(exc: BaseException) -> bool:
    return isinstance(exc, AccountThrottled) or isinstance(
        getattr(exc, "__cause__", None), AccountThrottled
    )


def register_admin_model_test_routes(
    app: FastAPI,
    require_admin: Callable[[Request], object | None],
    get_copilot_client: Callable[[Request], object],
) -> None:
    @app.post("/admin/model-test")
    async def model_test(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - any unparsable body is the same 400
            return _json_err(400, "invalid JSON body")
        if not isinstance(body, dict):
            return _json_err(400, "invalid JSON body")
        account_id = str(body.get("account_id") or "").strip()
        model = str(body.get("model") or "").strip()
        prompt = str(body.get("prompt") or "").strip() or _PROBE_PROMPT
        if not account_id or not model:
            return _json_err(400, "account_id and model are required")
        account = app.state.account_store.get(account_id)
        if account is None:
            return _json_err(404, "account not found")

        # The client factory reads only request.state, so a shim carrying this
        # account is enough to reuse the real /v1 path unchanged. api_key_obj is
        # None on purpose: a probe should measure the account, not inherit one
        # user's tone/prompt/timeout overrides.
        probe_request = SimpleNamespace(
            state=SimpleNamespace(account=account, api_key_obj=None)
        )
        result: dict = {
            "account_id": account_id,
            "account_name": account.name or account.id,
            "provider": getattr(account, "provider", "m365"),
            "model": model,
            "prompt": prompt,
        }
        try:
            client, resolved, is_consumer = apply_request_model(
                app, probe_request, get_copilot_client, model
            )
        except ValueError as exc:
            return _json_err(400, str(exc))
        except HTTPException as exc:
            result.update(verdict="error", error=str(exc.detail), latency_ms=0, reply="")
            return result
        result["upstream_selector"] = resolved

        started = time.monotonic()
        try:
            reply = await asyncio.wait_for(
                client.chat(prompt, [], None, None), timeout=_PROBE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            result.update(
                verdict="error",
                error=f"no response within {int(_PROBE_TIMEOUT_SECONDS)}s",
                latency_ms=int((time.monotonic() - started) * 1000),
                reply="",
            )
            return result
        except (SubstrateCopilotError, ConsumerCopilotError, HTTPException, OSError) as exc:
            detail = str(getattr(exc, "detail", "") or exc)
            result.update(
                verdict=classify_probe("", detail, throttled=_is_throttled(exc)),
                error=detail,
                latency_ms=int((time.monotonic() - started) * 1000),
                reply="",
            )
            return result
        result.update(
            verdict=classify_probe(reply),
            error="",
            latency_ms=int((time.monotonic() - started) * 1000),
            reply=reply[:_PREVIEW_CHARS],
            reply_len=len(reply),
        )
        return result
