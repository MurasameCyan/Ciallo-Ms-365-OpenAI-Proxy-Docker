from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_METRICS_HISTORY_LIMIT = 500


def _load_metrics_history(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)][-_METRICS_HISTORY_LIMIT:]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _write_metrics_history(path: Path, history: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(history[-_METRICS_HISTORY_LIMIT:], ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def init_metrics_store(state: Any, path: Path) -> None:
    state.metrics_path = path
    state.metrics_history = _load_metrics_history(path)
    state.metrics_last_snapshot = 0.0


def maybe_snapshot_metrics(state: Any, min_interval: float = 300.0) -> None:
    now = time.time()
    if now - getattr(state, "metrics_last_snapshot", 0.0) < min_interval:
        return
    state.metrics_last_snapshot = now
    keys = state.key_store.list()
    accts = state.account_store.list()
    valid = sum(1 for a in accts if a.token_status().get("valid"))
    snap = {
        "ts": now,
        "users": len(keys),
        "accounts": len(accts),
        "enabled_users": sum(1 for k in keys if k.enabled),
        "valid_accounts": valid,
        "expired_accounts": len(accts) - valid,
    }
    history = state.metrics_history
    history.append(snap)
    if len(history) > _METRICS_HISTORY_LIMIT:
        del history[:-_METRICS_HISTORY_LIMIT]
    _write_metrics_history(state.metrics_path, history)


def get_metrics_history_store(state: Any) -> list[dict]:
    return getattr(state, "metrics_history", [])


def clear_metrics_history_store(state: Any) -> None:
    state.metrics_history = []
    state.metrics_last_snapshot = time.time()
    _write_metrics_history(state.metrics_path, state.metrics_history)
