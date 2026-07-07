from __future__ import annotations

import time
from collections import deque
from typing import Any


def init_image_proxy_events(state: Any, limit: int = 100) -> None:
    state.image_proxy_events = []
    state.image_proxy_events_version = 0
    state.image_proxy_events_limit = limit


def append_image_proxy_event(state: Any, trace_id: str, phase: str, **fields: Any) -> dict[str, Any]:
    event = {
        "ts": time.time(),
        "trace_id": trace_id,
        "phase": phase,
        **fields,
    }
    events = list(getattr(state, "image_proxy_events", []))
    events.append(event)
    limit = int(getattr(state, "image_proxy_events_limit", 100) or 100)
    if len(events) > limit:
        events = list(deque(events, maxlen=limit))
    state.image_proxy_events = events
    state.image_proxy_events_version = int(getattr(state, "image_proxy_events_version", 0)) + 1
    return event


def get_image_proxy_events(state: Any, version: int | None = None) -> dict[str, Any]:
    events = list(getattr(state, "image_proxy_events", []))
    current_version = int(getattr(state, "image_proxy_events_version", 0))
    if version is not None and version == current_version:
        return {"version": current_version, "unchanged": True, "count": len(events), "events": []}
    return {"version": current_version, "count": len(events), "events": events}


def clear_image_proxy_events(state: Any) -> dict[str, Any]:
    state.image_proxy_events = []
    state.image_proxy_events_version = int(getattr(state, "image_proxy_events_version", 0)) + 1
    return {"status": "ok", "version": state.image_proxy_events_version}
