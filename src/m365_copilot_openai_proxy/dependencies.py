from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request

from .account_store import resolve_account_proxy
from .config import Settings
from .substrate_client import SubstrateCopilotClient


_CAPTURE_LIMIT = 20


def _attach_response_debug_sink(app: FastAPI, client: SubstrateCopilotClient) -> None:
    def sink(payload: dict) -> None:
        if not getattr(app.state, "capture_enabled", False):
            return
        captured = list(getattr(app.state, "captured_payloads", []))
        captured.append({"source": "copilot_response", "payload": payload})
        app.state.captured_payloads = captured[-_CAPTURE_LIMIT:]
        app.state.capture_payload_version = int(getattr(app.state, "capture_payload_version", 0)) + 1

    try:
        client._response_debug_sink = sink
    except Exception:
        return


def _consumer_gate_for(app: FastAPI, account_id: str):
    """Build the mid-request credential re-mint for one consumer account.

    ConsumerCopilotClient calls this at most once per turn, and only on a
    ClearanceRequired raised before any output. Routing it through the scheduler
    rather than straight at CamoufoxConsumerGate buys three things: the re-minted
    credential is persisted, so the next request starts fresh; the single-browser
    lock is respected, so this cannot run alongside a Chromium refresh; and the
    identity type the userscript captured survives, which a raw gate would blank
    out (MSAL mints no X-UserIdentityType).

    Returns None when there is no scheduler to route through, which leaves the
    client's gate unset and its original error intact.
    """
    scheduler = getattr(app.state, "refresh_scheduler", None)
    if scheduler is None:
        return None

    async def gate() -> dict:
        from .consumer_client import ClearanceRequired

        if not await scheduler.refresh_consumer(account_id):
            # Every failure mode here -- browser absent, launch broken, MSA
            # session lapsed -- needs the same human step, so say that rather
            # than leaking which one it was.
            raise ClearanceRequired(
                "Consumer credentials expired and the unattended refresh could "
                "not renew them. Re-push them from the userscript."
            )
        account = app.state.account_store.get(account_id)
        if account is None:
            raise ClearanceRequired("Consumer account disappeared mid-refresh.")
        from .consumer_gate import _pick_cookies

        return {
            "cookies": _pick_cookies(account.cookies or []),
            "access_token": getattr(account, "consumer_token", ""),
            "identity_type": getattr(account, "consumer_identity_type", ""),
        }

    return gate


def create_api_dependencies(
    app: FastAPI,
) -> tuple[Callable[[], Settings], Callable[[Request], SubstrateCopilotClient]]:
    def get_settings() -> Settings:
        return app.state.settings

    def get_copilot_client(raw_request: Request) -> SubstrateCopilotClient:
        try:
            key_obj = getattr(raw_request.state, "api_key_obj", None)
            account = getattr(raw_request.state, "account", None)
            token = account.token if account is not None else None
            tone = key_obj.tone if key_obj is not None else None
            global_tp = (getattr(app.state, "tool_prompt", "") or "").strip()
            key_tp = ((key_obj.tool_prompt if key_obj is not None else "") or "").strip()
            tool_prompt = "\n\n".join(p for p in (global_tp, key_tp) if p) or None
            time_zone = getattr(key_obj, "time_zone", "") or getattr(app.state, "time_zone", "Asia/Shanghai")
            # Idle timeout resolution: per-key override (minutes, 0 => inherit) wins,
            # else the global runtime setting, else the client default. Passed in seconds.
            key_idle_min = int(getattr(key_obj, "ws_idle_timeout_minutes", 0) or 0) if key_obj is not None else 0
            global_idle_min = int(getattr(app.state, "ws_idle_timeout_minutes", 0) or 0)
            idle_min = key_idle_min or global_idle_min
            idle_timeout = idle_min * 60 if idle_min > 0 else None
            # Consumer (personal-account) Copilot is a different protocol with a
            # different error type. Dispatch here -- the single point every /v1
            # route funnels through -- so no route needs per-provider branching.
            # The adapter presents the Substrate contract and translates errors;
            # the client rides this account's own egress when it has one, else
            # the process-global proxy env (curl_cffi honours that by default).
            # The split exists because consumer Copilot and M365 are gated
            # differently per source IP. A gate is attached so
            # an expired credential re-mints itself once mid-request instead of
            # failing the turn; it degrades to the userscript re-push when the
            # optional browser is absent.
            if account is not None and getattr(account, "provider", "m365") == "consumer":
                from .consumer_adapter import ConsumerClientAdapter
                from .consumer_client import ConsumerCopilotClient
                from .consumer_gate import _pick_cookies

                factory = getattr(app.state, "consumer_client_factory", None) or (
                    lambda **kwargs: ConsumerCopilotClient(**kwargs)
                )
                consumer = factory(
                    cookies=_pick_cookies(account.cookies or []),
                    access_token=getattr(account, "consumer_token", ""),
                    identity_type=getattr(account, "consumer_identity_type", ""),
                    idle_timeout=idle_timeout,
                    proxy=resolve_account_proxy(account) or None,
                    gate=_consumer_gate_for(app, account.id),
                )
                return ConsumerClientAdapter(
                    consumer,
                    max_prompt_chars=getattr(
                        getattr(app.state, "settings", None),
                        "consumer_prompt_max_chars",
                        8000,
                    ),
                )
            try:
                client = app.state.copilot_client_factory(token=token, tone=tone, tool_prompt=tool_prompt, time_zone=time_zone, idle_timeout=idle_timeout)
            except TypeError:
                # A factory that accepts no kwargs still has to work. Scoped to
                # this one call on purpose: while the whole body was covered, any
                # TypeError raised building the *consumer* client -- a renamed
                # kwarg, an adapter signature drift -- silently handed back an
                # anonymous M365 client instead, and the turn then failed with an
                # unrelated M365 error that named nothing about the real cause.
                client = app.state.copilot_client_factory()
            _attach_response_debug_sink(app, client)
            return client
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return get_settings, get_copilot_client
