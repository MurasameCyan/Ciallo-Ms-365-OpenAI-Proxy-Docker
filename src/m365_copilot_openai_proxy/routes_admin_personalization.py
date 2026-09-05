"""``/admin/accounts/{id}/personalization`` -- read and move the account flags.

Admin-only on purpose. These are settings on the operator's own Microsoft
account: they change what their web and phone Copilot does, not just what this
bridge sends, so a bound user must not be able to reach them.

The POST answers with what the account reads back after the write, never with
what was asked for -- see ``personalization`` for the two measured rules that
force that.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request

from .personalization import PersonalizationError, read_flags, write_flags
from .response_helpers import _json_err


def register_admin_personalization_routes(
    app: FastAPI, require_admin: Callable[[Request], object | None]
) -> None:
    @app.get("/admin/accounts/{acc_id}/personalization")
    async def get_personalization(acc_id: str, request: Request):
        err = require_admin(request)
        if err: return err
        if app.state.account_store.get(acc_id) is None:
            return _json_err(404, "Account not found")
        try:
            state = await read_flags(app.state.account_store, acc_id)
        except PersonalizationError as exc:
            return _json_err(exc.status, str(exc))
        return {"status": "ok", **state}

    @app.post("/admin/accounts/{acc_id}/personalization")
    async def set_personalization(acc_id: str, request: Request):
        err = require_admin(request)
        if err: return err
        if app.state.account_store.get(acc_id) is None:
            return _json_err(404, "Account not found")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - a malformed body is a client error
            body = None
        if not isinstance(body, dict):
            return _json_err(400, "请求体必须是一个 JSON 对象")
        try:
            state = await write_flags(app.state.account_store, acc_id, body)
        except ValueError as exc:
            return _json_err(400, str(exc))
        except PersonalizationError as exc:
            return _json_err(exc.status, str(exc))
        return {"status": "ok", **state}
