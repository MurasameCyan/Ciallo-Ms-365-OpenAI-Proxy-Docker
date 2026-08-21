"""Small persistent store for estimated API usage.

The upstream does not expose token counts.  These values are deliberately
labelled estimated and are kept independently from the bounded call log so an
operator can trim diagnostic records without resetting the site-wide total.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

from .atomic_write import write_text_atomic


_log = logging.getLogger("copilot_proxy")
_MAX_MODEL_NAME_CHARS = 80
_MAX_MODEL_BUCKETS = 25
_OTHER_MODEL = "other"


def estimate_text_tokens(value: Any) -> int:
    """Return a stable, dependency-free token estimate for display/telemetry.

    ASCII text is approximated at four characters per token; non-ASCII
    characters count individually. This is not a billing tokenizer.
    """
    if value is None:
        return 0
    text = str(value)
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return math.ceil(ascii_chars / 4) + non_ascii_chars


def estimate_upstream_input_tokens(prompt: Any, additional_context: Any = ()) -> int:
    """Estimate one request's input from its prompt and translated context."""
    if isinstance(additional_context, (str, bytes)):
        additional_context = [additional_context]
    return estimate_text_tokens(prompt) + sum(
        estimate_text_tokens(item) for item in (additional_context or ())
    )


def openai_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    return {
        "prompt_tokens": _nonnegative_int(usage.get("input_tokens")),
        "completion_tokens": _nonnegative_int(usage.get("output_tokens")),
        "total_tokens": _nonnegative_int(usage.get("total_tokens")),
        "estimated": True,
    }


def anthropic_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    return {
        "input_tokens": _nonnegative_int(usage.get("input_tokens")),
        "output_tokens": _nonnegative_int(usage.get("output_tokens")),
        "estimated": True,
    }


def responses_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    inp = _nonnegative_int(usage.get("input_tokens"))
    out = _nonnegative_int(usage.get("output_tokens"))
    return {
        "input_tokens": inp,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": out,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": _nonnegative_int(usage.get("total_tokens")),
        "estimated": True,
    }


def usage_for_record(record: dict[str, Any] | None) -> dict[str, Any]:
    """Return the current estimate for a call without recording it."""
    record = record or {}
    existing = record.get("usage")
    if isinstance(existing, dict):
        return dict(existing)
    inp = _nonnegative_int(record.get("usage_input_tokens"))
    out = _nonnegative_int(
        record.get("usage_output_tokens", estimate_text_tokens(record.get("response_text", "")))
    )
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "estimated": True,
    }


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _empty_data() -> dict[str, Any]:
    return {
        "version": 1,
        "calls_total": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "models": {},
    }


def _model_name(value: Any) -> str:
    name = " ".join(str(value or "").split()) or "unknown"
    return name[:_MAX_MODEL_NAME_CHARS]


def _empty_model_data() -> dict[str, int]:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _add_model_data(target: dict[str, int], *, calls: Any, input_tokens: Any, output_tokens: Any) -> None:
    inp = _nonnegative_int(input_tokens)
    out = _nonnegative_int(output_tokens)
    target["calls"] += _nonnegative_int(calls)
    target["input_tokens"] += inp
    target["output_tokens"] += out
    target["total_tokens"] += inp + out


def _bounded_model_bucket(models: dict[str, dict[str, int]], model: Any) -> str:
    name = _model_name(model)
    if name in models or name == _OTHER_MODEL:
        return name
    specific_count = sum(1 for existing in models if existing != _OTHER_MODEL)
    if specific_count < _MAX_MODEL_BUCKETS - 1:
        return name
    return _OTHER_MODEL


class UsageStore:
    """Process-local locked accumulator persisted as one atomic JSON document."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return _empty_data()
        if not isinstance(raw, dict):
            return _empty_data()
        data = _empty_data()
        for key in ("calls_total", "input_tokens", "output_tokens", "total_tokens"):
            data[key] = _nonnegative_int(raw.get(key))
        models = raw.get("models")
        if isinstance(models, dict):
            for model, item in models.items():
                if not isinstance(item, dict):
                    continue
                name = _bounded_model_bucket(data["models"], model)
                model_data = data["models"].setdefault(name, _empty_model_data())
                _add_model_data(
                    model_data,
                    calls=item.get("calls"),
                    input_tokens=item.get("input_tokens"),
                    output_tokens=item.get("output_tokens"),
                )
        return data

    def _save(self) -> None:
        write_text_atomic(
            self.path,
            json.dumps(self._data, ensure_ascii=False, separators=(",", ":")),
            mode=0o600,
        )

    def _save_best_effort(self) -> None:
        try:
            self._save()
        except Exception as exc:
            _log.warning("Unable to persist estimated usage stats: %s", exc)

    def record(self, model: Any, *, input_tokens: Any = 0, output_tokens: Any = 0) -> dict[str, Any]:
        """Add one completed call and return its estimated usage object."""
        inp = _nonnegative_int(input_tokens)
        out = _nonnegative_int(output_tokens)
        total = inp + out
        with self._lock:
            self._data["calls_total"] += 1
            self._data["input_tokens"] += inp
            self._data["output_tokens"] += out
            self._data["total_tokens"] += total
            model_name = _bounded_model_bucket(self._data["models"], model)
            model_data = self._data["models"].setdefault(
                model_name,
                _empty_model_data(),
            )
            _add_model_data(model_data, calls=1, input_tokens=inp, output_tokens=out)
            self._save_best_effort()
        return {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": total,
            "estimated": True,
        }

    def finalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Record a call once, deriving missing output from response text."""
        if record.get("usage_recorded"):
            return dict(record.get("usage") or {})
        usage = self.record(
            record.get("model"),
            input_tokens=record.get("usage_input_tokens", 0),
            output_tokens=record.get(
                "usage_output_tokens",
                estimate_text_tokens(record.get("response_text", "")),
            ),
        )
        record["usage"] = usage
        record["usage_recorded"] = True
        return usage

    def summary(self) -> dict[str, Any]:
        with self._lock:
            models = self._data["models"]
            return {
                "calls_total": self._data["calls_total"],
                "input_tokens": self._data["input_tokens"],
                "output_tokens": self._data["output_tokens"],
                "total_tokens": self._data["total_tokens"],
                "estimated": True,
                "model_counts": {
                    name: int(item.get("calls", 0))
                    for name, item in models.items()
                    if int(item.get("calls", 0)) > 0
                },
            }

    def clear(self) -> None:
        with self._lock:
            self._data = _empty_data()
            self._save_best_effort()
