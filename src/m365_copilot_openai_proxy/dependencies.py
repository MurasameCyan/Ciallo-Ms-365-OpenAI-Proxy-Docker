from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .substrate_client import SubstrateCopilotClient


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
            return app.state.copilot_client_factory(token=token, tone=tone, tool_prompt=tool_prompt, time_zone=time_zone)
        except TypeError:
            return app.state.copilot_client_factory()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return get_settings, get_copilot_client
