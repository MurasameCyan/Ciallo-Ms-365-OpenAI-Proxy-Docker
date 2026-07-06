from __future__ import annotations

import json
import time
from collections.abc import Callable

from fastapi import FastAPI, Request

from .response_helpers import _json_err


_CAPTURE_MAX_BYTES = 256 * 1024


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
            if st.get("valid") and rem is not None and 0 <= rem <= 600:
                expiring_accounts.append({"name": a.name or a.id, "email": a.email, "seconds_remaining": rem})
        expiring_accounts.sort(key=lambda x: x["seconds_remaining"])
        return {
            "calls_total": len(logs),
            "calls_24h": calls_24h,
            "tone_counts": tone_counts,
            "expiring_accounts": expiring_accounts,
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
        return {"status": "ok", "count": len(app.state.captured_payloads)}

    @app.get("/admin/capture-payload")
    async def get_captured_payload(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"payloads": getattr(app.state, 'captured_payloads', [])}

    @app.post("/admin/capture-payload/clear")
    async def clear_captured_payload(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        app.state.captured_payloads = []
        return {"status": "ok"}

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
