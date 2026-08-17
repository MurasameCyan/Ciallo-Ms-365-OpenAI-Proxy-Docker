from __future__ import annotations

import json
import time
from collections.abc import Callable

from fastapi import FastAPI, Request

from .m365_cloud_client import token_cache_stats
from .response_helpers import _json_err


_CAPTURE_MAX_BYTES = 256 * 1024


def _cache_stats(app: FastAPI, logs: list) -> dict:
    """What the session/token caches are actually buying.

    ``incremental`` is already recorded per call: True means the turn continued a
    remembered upstream conversation and only the new message was sent, False
    means the whole transcript had to be resent. That ratio is the one number that
    says whether session reuse is working; the rest exposes the two in-memory
    caches behind it and how many disk writes the coalescing window saved.
    """
    incremental_hits = sum(1 for entry in logs if entry.get("incremental") is True)
    fresh_starts = sum(1 for entry in logs if entry.get("incremental") is False)
    resumable = incremental_hits + fresh_starts
    store = getattr(app.state, "session_store", None)
    index = getattr(app.state, "history_index", None)
    return {
        "incremental_hits": incremental_hits,
        "fresh_starts": fresh_starts,
        "incremental_hit_rate": (
            round(incremental_hits / resumable, 4) if resumable else None
        ),
        "sessions": store.stats() if store is not None else {},
        "history_index": index.stats() if index is not None else {},
        "cloud_token": token_cache_stats(),
    }


def register_admin_debug_routes(app: FastAPI, require_admin: Callable[[Request], object | None]) -> None:
    @app.get("/admin/stats")
    async def get_stats(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        now = time.time()
        logs = getattr(app.state, 'call_log', [])
        calls_24h = sum(1 for l in logs if (now - l.get("ts", 0)) <= 86400)
        tone_counts: dict[str, int] = {}
        for l in logs:
            tn = l.get("tone") or "Magic"
            tone_counts[tn] = tone_counts.get(tn, 0) + 1
        # Accounts expiring within 10 minutes, for the account-page warning carousel.
        expiring_accounts = []
        for a in app.state.account_store.list():
            st = a.token_status()
            rem = st.get("seconds_remaining")
            expires_at = st.get("expires_at")
            if st.get("valid") and expires_at not in (None, "") and rem is not None and 0 <= rem <= 600:
                expiring_accounts.append({"name": a.name or a.id, "email": a.email, "seconds_remaining": rem})
        expiring_accounts.sort(key=lambda x: x["seconds_remaining"])
        return {
            "calls_total": len(logs),
            "calls_24h": calls_24h,
            "tone_counts": tone_counts,
            "expiring_accounts": expiring_accounts,
            "cache": _cache_stats(app, logs),
        }

    @app.post("/admin/capture-payload")
    async def capture_payload(request: Request) -> dict:
        # Gate first, parse last — reject cheaply before touching the body.
        # The Tampermonkey script pushes cross-origin and cannot carry the
        # admin cookie, so the debug-page toggle is the gate here (not admin
        # auth): when off, every push is rejected outright.
        if not getattr(app.state, "capture_enabled", False):
            return _json_err(403, "capture receiving is disabled")
        # body size limit (avoid parsing huge junk payloads)
        try:
            clen = int(request.headers.get("content-length") or 0)
        except ValueError:
            clen = 0
        if clen > _CAPTURE_MAX_BYTES:
            return _json_err(413, "payload too large")
        raw = await request.body()
        if len(raw) > _CAPTURE_MAX_BYTES:
            return _json_err(413, "payload too large")
        try:
            body = json.loads(raw or b"{}")
        except (ValueError, TypeError):
            return _json_err(400, "invalid json")
        payloads = body.get("payloads", [])
        if not isinstance(payloads, list):
            return _json_err(400, "payloads must be a list")
        app.state.captured_payloads = payloads[:20]
        app.state.capture_payload_version = int(getattr(app.state, "capture_payload_version", 0)) + 1
        return {"status": "ok", "count": len(app.state.captured_payloads), "version": app.state.capture_payload_version}

    @app.get("/admin/capture-payload")
    async def get_captured_payload(request: Request, version: int | None = None) -> dict:
        err = require_admin(request)
        if err: return err
        payloads = getattr(app.state, 'captured_payloads', [])
        current_version = int(getattr(app.state, 'capture_payload_version', 0))
        if version is not None and version == current_version:
            return {"version": current_version, "unchanged": True, "count": len(payloads), "payloads": []}
        return {"version": current_version, "count": len(payloads), "payloads": payloads}

    @app.post("/admin/capture-payload/clear")
    async def clear_captured_payload(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        app.state.captured_payloads = []
        app.state.capture_payload_version = int(getattr(app.state, "capture_payload_version", 0)) + 1
        return {"status": "ok", "version": app.state.capture_payload_version}

    @app.get("/admin/capture-toggle")
    async def get_capture_toggle(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"enabled": bool(getattr(app.state, "capture_enabled", False))}

    @app.post("/admin/capture-toggle")
    async def set_capture_toggle(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        app.state.capture_enabled = bool(body.get("enabled"))
        return {"enabled": app.state.capture_enabled}
