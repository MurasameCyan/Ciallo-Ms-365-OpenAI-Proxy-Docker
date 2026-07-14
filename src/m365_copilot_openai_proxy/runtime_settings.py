from __future__ import annotations

import json
import re
from pathlib import Path

from .tone_options import TONE_OPTIONS as _BUILTIN_TONE_OPTIONS

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_RUN_PERMISSIONS = {"read_only", "full"}
_MEDIA_SUFFIX_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,39}$")
_DEFAULT_MEDIA_PROXY_SUFFIXES = [
    "png", "jpg", "jpeg", "webp", "gif", "svg", "bmp", "tif", "tiff", "ico", "heic", "heif", "avif",
    "wav", "mp3", "m4a", "ogg", "oga", "flac", "aac", "opus", "wma", "mid", "midi",
    "mp4", "webm", "mov", "mkv", "avi", "m4v", "3gp", "wmv", "flv", "mpeg", "mpg",
    "pdf", "txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "xml", "html", "htm", "yaml", "yml", "toml", "ini", "env",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf",
    "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "tar.gz", "tar.bz2", "tar.xz",
    "py", "pyw", "js", "mjs", "cjs", "ts", "tsx", "jsx", "java", "go", "rs", "c", "h", "cpp", "cxx", "cc", "hpp", "cs",
    "php", "rb", "swift", "kt", "kts", "scala", "sh", "bash", "zsh", "fish", "ps1", "bat", "cmd", "sql", "r", "lua", "pl", "pm",
    "vue", "svelte", "css", "scss", "sass", "less", "dockerfile", "makefile", "cmake", "gradle", "lock", "log", "conf", "cfg",
]
_RUNTIME_SETTINGS_DEFAULTS = {
    "time_zone": "Asia/Shanghai",
    "model_alias": "m365-copilot",
    "auto_refresh": True,
    "refresh_before_seconds": 300,
    "idle_timeout_minutes": 30,
    # Chat WebSocket idle timeout (minutes): max gap between upstream frames before
    # a stalled connection is aborted. Heartbeats/deltas reset it, so this only trips
    # on a genuinely silent upstream. Per-user keys may override (0 => inherit this).
    "ws_idle_timeout_minutes": 5,
    # Cookie keepalive: how often the background loop scans the account pool
    # (minutes), and how long before a cookie's expiry it proactively refreshes
    # (hours). Refreshes are serialised (one Chromium at a time). See RefreshScheduler.
    "keepalive_check_minutes": 5,
    "cookie_keepalive_before_hours": 2,
    "cdp_port": 9222,
    "account_cdp_port_base": 9322,
    "log_level": "INFO",
    "call_log_limit": 100,
    "run_permission": "full",
    # User/account runtime log toggles (see runtime_flags.py). verbose gates normal
    # progress logs, errors gates failure logs. Seeded from .env on first boot; the
    # persisted file wins once written, and the admin UI can flip them at runtime.
    "user_log_verbose": True,
    "user_log_errors": True,
    "media_proxy_suffixes": list(_DEFAULT_MEDIA_PROXY_SUFFIXES),
    # Signed media proxy URL lifetime. The upstream designer/media auth token is
    # refreshed alongside cookies, so the fetch itself always uses the freshest
    # token; this TTL only governs how long a signed URL already stored in a
    # client's chat history stays resolvable. Default 30 days keeps historical
    # images alive far beyond the old 10-minute window.
    "media_proxy_ttl_seconds": 30 * 24 * 60 * 60,
    # Conversation modes shown in the picker. Each entry is
    # {value, label_zh, label_en}; `value` is the raw tone sent to M365 (any
    # string, so future upstream modes work without a code change) and the labels
    # are the editable display names. Defaults to the built-in list.
    "tone_options": [dict(o) for o in _BUILTIN_TONE_OPTIONS],
}

# Max entries / field lengths to keep the picker and persisted file bounded.
_MAX_TONE_OPTIONS = 40
_MAX_TONE_FIELD_LEN = 80


def _sanitize_tone_label(label: str) -> str:
    """Collapse whitespace to underscores so a display name is safe to use as a
    model id in OpenAI-compatible clients (many clients break on spaces when a
    model is added manually)."""
    return re.sub(r"\s+", "_", label.strip())


def normalize_tone_options(value) -> list[dict]:
    """Coerce admin input into a clean list of {value,label,label_zh,label_en}.

    Accepts either a list of dicts (from JSON) or a newline-delimited string
    (from the textarea editor) where each line is `value | display_name`
    (display name optional; defaults to the tone value). Display names have
    their whitespace collapsed to underscores so each tone can double as a
    model id. Blank/duplicate values are dropped. Falls back to the built-in
    list when nothing valid remains so the picker is never empty.
    """
    raw_items: list = []
    if isinstance(value, str):
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            val = parts[0]
            label = parts[1] if len(parts) > 1 and parts[1] else val
            raw_items.append({"value": val, "label_zh": label})
    elif isinstance(value, list):
        raw_items = value

    options: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        val = str(item.get("value") or "").strip()[:_MAX_TONE_FIELD_LEN]
        if not val or val in seen:
            continue
        label = str(item.get("label_zh") or item.get("label") or item.get("label_en") or val).strip()[:_MAX_TONE_FIELD_LEN]
        label = _sanitize_tone_label(label) or val
        seen.add(val)
        # label_en kept equal to label for backward-compatible serialization.
        options.append({"value": val, "label": label, "label_zh": label, "label_en": label})
        if len(options) >= _MAX_TONE_OPTIONS:
            break
    if not options:
        options = [dict(o) for o in _BUILTIN_TONE_OPTIONS]
    return options


def normalize_media_proxy_suffixes(value) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\s,;]+", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    suffixes: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        suffix = str(item or "").strip().lower().lstrip(".")
        if not suffix or suffix in seen or not _MEDIA_SUFFIX_RE.match(suffix):
            continue
        seen.add(suffix)
        suffixes.append(suffix)
    return suffixes


def _runtime_settings_path(token_dir: str) -> Path:
    return Path(token_dir) / "runtime_settings.json"


def _read_runtime_settings(token_dir: str, env_defaults: dict | None = None) -> dict:
    data = dict(_RUNTIME_SETTINGS_DEFAULTS)
    # .env-provided defaults layer on top of the static defaults but UNDER the
    # persisted file, giving precedence: file > .env > static default.
    if env_defaults:
        data.update({k: env_defaults[k] for k in data.keys() if k in env_defaults})
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
    data["ws_idle_timeout_minutes"] = max(1, int(data.get("ws_idle_timeout_minutes") or _RUNTIME_SETTINGS_DEFAULTS["ws_idle_timeout_minutes"]))
    data["keepalive_check_minutes"] = max(1, int(data.get("keepalive_check_minutes") or _RUNTIME_SETTINGS_DEFAULTS["keepalive_check_minutes"]))
    data["cookie_keepalive_before_hours"] = max(1, int(data.get("cookie_keepalive_before_hours") or _RUNTIME_SETTINGS_DEFAULTS["cookie_keepalive_before_hours"]))
    data["cdp_port"] = max(1, int(data.get("cdp_port") or _RUNTIME_SETTINGS_DEFAULTS["cdp_port"]))
    data["account_cdp_port_base"] = max(1, int(data.get("account_cdp_port_base") or _RUNTIME_SETTINGS_DEFAULTS["account_cdp_port_base"]))
    data["log_level"] = str(data.get("log_level") or _RUNTIME_SETTINGS_DEFAULTS["log_level"]).strip().upper()
    if data["log_level"] not in _LOG_LEVELS:
        data["log_level"] = _RUNTIME_SETTINGS_DEFAULTS["log_level"]
    data["call_log_limit"] = max(1, int(data.get("call_log_limit") or _RUNTIME_SETTINGS_DEFAULTS["call_log_limit"]))
    data["run_permission"] = str(data.get("run_permission") or _RUNTIME_SETTINGS_DEFAULTS["run_permission"]).strip()
    if data["run_permission"] not in _RUN_PERMISSIONS:
        data["run_permission"] = _RUNTIME_SETTINGS_DEFAULTS["run_permission"]
    data["user_log_verbose"] = bool(data.get("user_log_verbose"))
    data["user_log_errors"] = bool(data.get("user_log_errors"))
    data["media_proxy_suffixes"] = normalize_media_proxy_suffixes(data.get("media_proxy_suffixes")) or list(_DEFAULT_MEDIA_PROXY_SUFFIXES)
    data["tone_options"] = normalize_tone_options(data.get("tone_options"))
    try:
        data["media_proxy_ttl_seconds"] = max(60, int(data.get("media_proxy_ttl_seconds") or 0))
    except (TypeError, ValueError):
        data["media_proxy_ttl_seconds"] = _RUNTIME_SETTINGS_DEFAULTS["media_proxy_ttl_seconds"]
    return data


def _write_runtime_settings(token_dir: str, data: dict) -> None:
    path = _runtime_settings_path(token_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
