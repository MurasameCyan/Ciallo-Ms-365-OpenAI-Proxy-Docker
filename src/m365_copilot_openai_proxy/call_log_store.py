from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .usage_store import estimate_text_tokens


def load_call_log(path: Path, limit: int) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)][-limit:]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def write_call_log(path: Path, data: list[dict], limit: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data[-limit:], ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _bump_call_log_version(state: Any) -> None:
    state.call_log_version = int(getattr(state, "call_log_version", 0)) + 1


def append_call_log(state: Any, record: dict) -> None:
    usage_store = getattr(state, "usage_store", None)
    if usage_store is not None and record.get("response_text") is not None:
        usage_store.finalize_record(record)
    state.call_log.append(record)
    limit = int(getattr(state, "call_log_limit", 100))
    if len(state.call_log) > limit:
        state.call_log = state.call_log[-limit:]
    _bump_call_log_version(state)
    write_call_log(state.call_log_path, state.call_log, limit)


def record_response_text(state: Any, record: dict, text: str) -> None:
    record["usage_output_tokens"] = estimate_text_tokens(text)
    record["response_len"] = len(text)
    record["response_text"] = text[:8000]
    record["response_repr"] = repr(text[:2000])
    if record.get("tool_calls_result") is None:
        record["tool_calls_result"] = []
    usage_store = getattr(state, "usage_store", None)
    if usage_store is not None:
        usage_store.finalize_record(record)
    _bump_call_log_version(state)
    write_call_log(state.call_log_path, state.call_log, int(getattr(state, "call_log_limit", 100)))


def clear_call_log(state: Any) -> None:
    state.call_log = []
    _bump_call_log_version(state)
    write_call_log(state.call_log_path, state.call_log, int(getattr(state, "call_log_limit", 100)))


def trim_call_log(state: Any) -> None:
    limit = int(getattr(state, "call_log_limit", 100))
    if len(state.call_log) > limit:
        state.call_log = state.call_log[-limit:]
        _bump_call_log_version(state)
        write_call_log(state.call_log_path, state.call_log, limit)
