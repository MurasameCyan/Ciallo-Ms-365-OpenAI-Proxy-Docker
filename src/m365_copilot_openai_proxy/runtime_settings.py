from __future__ import annotations

import json
from pathlib import Path

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_RUN_PERMISSIONS = {"read_only", "full"}
_RUNTIME_SETTINGS_DEFAULTS = {
    "time_zone": "Asia/Shanghai",
    "model_alias": "m365-copilot",
    "auto_refresh": True,
    "refresh_before_seconds": 300,
    "idle_timeout_minutes": 30,
    "cdp_port": 9222,
    "account_cdp_port_base": 9322,
    "log_level": "INFO",
    "call_log_limit": 100,
    "run_permission": "full",
}


def _runtime_settings_path(token_dir: str) -> Path:
    return Path(token_dir) / "runtime_settings.json"


def _read_runtime_settings(token_dir: str) -> dict:
    data = dict(_RUNTIME_SETTINGS_DEFAULTS)
    try:
        raw = json.loads(_runtime_settings_path(token_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    if isinstance(raw, dict):
        data.update({k: raw[k] for k in data.keys() if k in raw})
    data["time_zone"] = str(data.get("time_zone") or _RUNTIME_SETTINGS_DEFAULTS["time_zone"]).strip()
    data["model_alias"] = str(data.get("model_alias") or _RUNTIME_SETTINGS_DEFAULTS["model_alias"]).strip()
    data["auto_refresh"] = bool(data.get("auto_refresh"))
    data["refresh_before_seconds"] = max(0, int(data.get("refresh_before_seconds") or 0))
    data["idle_timeout_minutes"] = max(1, int(data.get("idle_timeout_minutes") or 1))
    data["cdp_port"] = max(1, int(data.get("cdp_port") or _RUNTIME_SETTINGS_DEFAULTS["cdp_port"]))
    data["account_cdp_port_base"] = max(1, int(data.get("account_cdp_port_base") or _RUNTIME_SETTINGS_DEFAULTS["account_cdp_port_base"]))
    data["log_level"] = str(data.get("log_level") or _RUNTIME_SETTINGS_DEFAULTS["log_level"]).strip().upper()
    if data["log_level"] not in _LOG_LEVELS:
        data["log_level"] = _RUNTIME_SETTINGS_DEFAULTS["log_level"]
    data["call_log_limit"] = max(1, int(data.get("call_log_limit") or _RUNTIME_SETTINGS_DEFAULTS["call_log_limit"]))
    data["run_permission"] = str(data.get("run_permission") or _RUNTIME_SETTINGS_DEFAULTS["run_permission"]).strip()
    if data["run_permission"] not in _RUN_PERMISSIONS:
        data["run_permission"] = _RUNTIME_SETTINGS_DEFAULTS["run_permission"]
    return data


def _write_runtime_settings(token_dir: str, data: dict) -> None:
    path = _runtime_settings_path(token_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
