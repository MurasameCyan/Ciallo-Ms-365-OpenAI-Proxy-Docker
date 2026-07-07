from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request

from .call_log_store import clear_call_log as clear_call_log_store
from .metrics_store import (
    clear_metrics_history_store,
    get_metrics_history_store,
    maybe_snapshot_metrics,
)


def register_admin_observability_routes(app: FastAPI, require_admin: Callable[[Request], object | None]) -> None:
    @app.get("/admin/call-log")
    async def get_call_log(request: Request, version: int | None = None) -> dict:
        err = require_admin(request)
        if err: return err
        logs = getattr(app.state, 'call_log', [])
        current_version = int(getattr(app.state, 'call_log_version', 0))
        if version is not None and version == current_version:
            return {"version": current_version, "unchanged": True, "count": len(logs), "logs": []}
        return {"version": current_version, "count": len(logs), "logs": logs}

    @app.post("/admin/call-log/clear")
    async def clear_call_log(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        clear_call_log_store(app.state)
        return {"status": "ok", "version": int(getattr(app.state, 'call_log_version', 0))}

    @app.get("/admin/metrics-history")
    async def get_metrics_history(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        maybe_snapshot_metrics(app.state)  # lazy, throttled snapshot on poll
        return {"history": get_metrics_history_store(app.state)}

    @app.post("/admin/metrics-history/clear")
    async def clear_metrics_history(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        clear_metrics_history_store(app.state)
        return {"status": "ok"}

    @app.get("/admin/summary")
    async def get_summary(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        accounts = app.state.account_store.list()
        keys = app.state.key_store.list()
        valid_accounts = sum(1 for a in accounts if a.token_status().get("valid"))
        enabled_keys = sum(1 for k in keys if k.enabled)
        bound_keys = sum(1 for k in keys if k.account_id)
        return {
            "accounts_total": len(accounts),
            "accounts_valid": valid_accounts,
            "accounts_expired": len(accounts) - valid_accounts,
            "keys_total": len(keys),
            "keys_enabled": enabled_keys,
            "keys_disabled": len(keys) - enabled_keys,
            "keys_bound": bound_keys,
            "keys_unbound": len(keys) - bound_keys,
        }
