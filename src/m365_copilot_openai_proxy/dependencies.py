from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request

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
            client = app.state.copilot_client_factory(token=token, tone=tone, tool_prompt=tool_prompt, time_zone=time_zone, idle_timeout=idle_timeout)
            _attach_response_debug_sink(app, client)
            return client
        except TypeError:
            client = app.state.copilot_client_factory()
            _attach_response_debug_sink(app, client)
            return client
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return get_settings, get_copilot_client
